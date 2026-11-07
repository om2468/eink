// Downloads the published page, adds the times and battery level, and sends it
// to the e-ink display over Bluetooth. Runs on the hour and half hour from 08:00
// to 19:00 UK time. The protocol is documented in the repo's README.
//
// Send "u" over the serial port to force an update, for testing.

#include <Adafruit_GFX.h>
#include <Arduino.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include <HTTPClient.h>
#include <NimBLEDevice.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>

#include "secrets.h"

static const char* PAGE_URL = "https://om2468.github.io/eink/page.bin";
static const char* DEVICE_NAME = "NRF_EPD_C0DC";
static const char* SERVICE_UUID = "62750001-d828-918d-fb46-b6c11c675aec";
static const char* COMMAND_CHAR_UUID = "62750002-d828-918d-fb46-b6c11c675aec";

static const char* TZ_UK = "GMT0BST,M3.5.0/1,M10.5.0";
static const char* TZ_NEW_YORK = "EST5EDT,M3.2.0,M11.1.0";

static const int FIRST_UPDATE_MINUTE = 8 * 60;
static const int LAST_UPDATE_MINUTE = 19 * 60;
static const int ATTEMPTS = 3;
static const uint32_t RETRY_DELAY_MS = 60 * 1000;

static const int WIDTH = 400;
static const int HEIGHT = 300;
static const int ROW_BYTES = WIDTH / 8;
static const int PLANE_SIZE = ROW_BYTES * HEIGHT;
static const int PAGE_SIZE = PLANE_SIZE * 2;
// Keep in step with HEADER_HEIGHT in dashboard/config.py.
static const int HEADER_HEIGHT = 28;

static const uint8_t EXPECTED_MODEL = 0x16;
static const int CONFIG_MODEL_INDEX = 7;

static const uint8_t CMD_INIT = 0x01;
static const uint8_t CMD_REFRESH = 0x05;
static const uint8_t CMD_WRITE_IMAGE = 0x30;
static const uint8_t FLAG_RED_PLANE = 0x01;
static const uint8_t FLAG_FIRST_CHUNK = 0x02;

static const int DEFAULT_ACK_INTERVAL = 10;
static const int MAX_ACK_INTERVAL = 50;
static const uint32_t REPLY_TIMEOUT_MS = 5000;
static const uint32_t BATTERY_REPLY_TIMEOUT_MS = 2000;
// Stay connected while the panel redraws. 30 seconds is known to work.
static const uint32_t REFRESH_WAIT_MS = 30 * 1000;
// The guide says 2.8 V means the battery is low.
static const int LOW_BATTERY_MV = 2800;

static uint8_t page[PAGE_SIZE];
static int lastSlot = -1;

struct Notification {
    size_t length;
    uint8_t data[64];
};
static QueueHandle_t notifications;

static void onNotify(NimBLERemoteCharacteristic*, uint8_t* data, size_t length, bool) {
    Notification item;
    item.length = min(length, sizeof(item.data));
    memcpy(item.data, data, item.length);
    xQueueSend(notifications, &item, 0);
}

static bool connectWifi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) delay(500);
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("Wi-Fi connection failed");
        return false;
    }
    configTzTime(TZ_UK, "pool.ntp.org", "time.google.com");
    return true;
}

static void disconnectWifi() {
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
}

static bool clockIsSet() {
    return time(nullptr) > 1700000000;
}

static bool waitForClock() {
    for (int i = 0; i < 40 && !clockIsSet(); i++) delay(500);
    return clockIsSet();
}

static bool downloadPage() {
    // The page is public and holds nothing sensitive, so the server's certificate
    // isn't verified. The worst case is a wrong picture.
    WiFiClientSecure client;
    client.setInsecure();

    // The query string avoids getting an older copy from a cache.
    String url = String(PAGE_URL) + "?t=" + String((unsigned long)time(nullptr));
    HTTPClient http;
    http.setTimeout(20000);
    if (!http.begin(client, url)) return false;

    int status = http.GET();
    int size = http.getSize();
    if (status != 200 || size != PAGE_SIZE) {
        Serial.printf("Download failed: status %d, size %d\n", status, size);
        http.end();
        return false;
    }

    WiFiClient* stream = http.getStreamPtr();
    int received = 0;
    uint32_t started = millis();
    while (received < PAGE_SIZE && millis() - started < 30000) {
        int available = stream->available();
        if (available > 0) {
            received += stream->readBytes(page + received, min(available, PAGE_SIZE - received));
        } else {
            delay(5);
        }
    }
    http.end();
    if (received != PAGE_SIZE) {
        Serial.printf("Download incomplete: %d bytes\n", received);
        return false;
    }
    return true;
}

static void localTimeIn(const char* zone, struct tm* out) {
    time_t now = time(nullptr);
    setenv("TZ", zone, 1);
    tzset();
    localtime_r(&now, out);
    setenv("TZ", TZ_UK, 1);
    tzset();
}

static void drawRightAligned(GFXcanvas1& canvas, const char* text, int right, int baseline) {
    int16_t x, y;
    uint16_t w, h;
    canvas.getTextBounds(text, 0, baseline, &x, &y, &w, &h);
    canvas.setCursor(right - w, baseline);
    canvas.print(text);
}

// Draws the header into the black and white plane. Canvas rows use the same
// layout as the panel, and a set bit is white, so it can be copied straight in.
static void drawHeader(int batteryMv) {
    struct tm uk, newYork;
    localTimeIn(TZ_UK, &uk);
    localTimeIn(TZ_NEW_YORK, &newYork);

    char left[32], ny[16], battery[20];
    strftime(left, sizeof(left), "%a %e %b  UK %H:%M", &uk);
    strftime(ny, sizeof(ny), "NY %H:%M", &newYork);
    if (batteryMv <= 0) {
        snprintf(battery, sizeof(battery), "Batt ?");
    } else {
        snprintf(battery, sizeof(battery), "%s %d.%02dV", batteryMv <= LOW_BATTERY_MV ? "LOW" : "Batt",
                 batteryMv / 1000, (batteryMv % 1000) / 10);
    }

    GFXcanvas1 canvas(WIDTH, HEADER_HEIGHT);
    canvas.fillScreen(0);
    canvas.setFont(&FreeSansBold9pt7b);
    canvas.setTextColor(1);
    canvas.setTextWrap(false);
    const int baseline = 20;
    canvas.setCursor(8, baseline);
    canvas.print(left);
    drawRightAligned(canvas, ny, 290, baseline);
    drawRightAligned(canvas, battery, WIDTH - 8, baseline);

    memcpy(page, canvas.getBuffer(), ROW_BYTES * HEADER_HEIGHT);
}

static bool nextNotification(Notification* item, uint32_t timeoutMs) {
    return xQueueReceive(notifications, item, pdMS_TO_TICKS(timeoutMs)) == pdTRUE;
}

static bool sendPlane(NimBLERemoteCharacteristic* command, const uint8_t* plane, bool isRed, int maxChunk,
                      int ackInterval) {
    static uint8_t packet[260];
    int sinceAck = 0;
    for (int offset = 0; offset < PLANE_SIZE; offset += maxChunk) {
        int length = min(maxChunk, PLANE_SIZE - offset);
        packet[0] = CMD_WRITE_IMAGE;
        packet[1] = (isRed ? FLAG_RED_PLANE : 0) | (offset == 0 ? FLAG_FIRST_CHUNK : 0);
        memcpy(packet + 2, plane + offset, length);

        bool needsAck = sinceAck >= ackInterval;
        if (!command->writeValue(packet, length + 2, needsAck)) {
            Serial.println("Image write failed");
            return false;
        }
        sinceAck = needsAck ? 0 : sinceAck + 1;
        if (!needsAck) delay(5);  // Give the display time, as nothing paces these writes.
    }
    return true;
}

// Talks to an already connected display.
static bool sendToClient(NimBLEClient* client) {
    NimBLERemoteService* service = client->getService(SERVICE_UUID);
    NimBLERemoteCharacteristic* command = service ? service->getCharacteristic(COMMAND_CHAR_UUID) : nullptr;
    if (!command) {
        Serial.println("Display service not found");
        return false;
    }

    xQueueReset(notifications);
    if (!command->subscribe(true, onNotify)) {
        Serial.println("Couldn't turn on notifications");
        return false;
    }

    // The display sends its config first. Check the model before changing anything.
    Notification item;
    if (!nextNotification(&item, REPLY_TIMEOUT_MS) || item.length <= CONFIG_MODEL_INDEX) {
        Serial.println("No config from display");
        return false;
    }
    if (item.data[CONFIG_MODEL_INDEX] != EXPECTED_MODEL) {
        Serial.printf("Unexpected display model 0x%02x\n", item.data[CONFIG_MODEL_INDEX]);
        return false;
    }

    if (!command->writeValue(&CMD_INIT, 1, true)) return false;

    int mtu = 0;
    int ackInterval = DEFAULT_ACK_INTERVAL;
    int batteryMv = 0;
    bool rle = false;
    uint32_t timeout = REPLY_TIMEOUT_MS;
    while (batteryMv == 0 && nextNotification(&item, timeout)) {
        String text((const char*)item.data, item.length);
        Serial.printf("Display: %s\n", text.c_str());
        if (text.startsWith("err=")) return false;
        if (text.startsWith("mtu=")) {
            mtu = text.substring(4).toInt();
            rle = text.indexOf("rle=1") >= 0;
            int intl = text.indexOf("intl=");
            if (intl >= 0) ackInterval = min(MAX_ACK_INTERVAL, (int)text.substring(intl + 5).toInt());
            timeout = BATTERY_REPLY_TIMEOUT_MS;  // The time and battery reply follows.
        }
        int bat = text.indexOf("bat=");
        if (bat >= 0) batteryMv = text.substring(bat + 4).toInt();
    }
    // rle=1 marks the firmware generation whose image flags are used here.
    if (mtu <= 2 || !rle) {
        Serial.println("Display didn't report a supported session");
        return false;
    }
    delay(200);

    drawHeader(batteryMv);

    int maxChunk = min(mtu, client->getMTU() - 3) - 2;
    Serial.printf("Sending: chunk %d, ack every %d, battery %d mV\n", maxChunk, ackInterval, batteryMv);
    if (!sendPlane(command, page, false, maxChunk, ackInterval)) return false;
    if (!sendPlane(command, page + PLANE_SIZE, true, maxChunk, ackInterval)) return false;

    delay(300);
    if (!command->writeValue(&CMD_REFRESH, 1, true)) return false;
    delay(REFRESH_WAIT_MS);
    return true;
}

static bool sendToDisplay() {
    NimBLEScan* scan = NimBLEDevice::getScan();
    scan->setActiveScan(true);
    NimBLEScanResults results = scan->getResults(20000, false);

    const NimBLEAdvertisedDevice* found = nullptr;
    for (int i = 0; i < results.getCount(); i++) {
        const NimBLEAdvertisedDevice* device = results.getDevice(i);
        if (device->getName() == DEVICE_NAME) {
            found = device;
            break;
        }
    }
    if (!found) {
        Serial.println("Display not found. Is a browser connected to it?");
        return false;
    }

    NimBLEClient* client = NimBLEDevice::createClient();
    bool ok = client->connect(found) && sendToClient(client);
    // Always disconnect: staying connected drains the display's battery quickly.
    if (client->isConnected()) client->disconnect();
    delay(500);
    NimBLEDevice::deleteClient(client);
    scan->clearResults();
    return ok;
}

static bool update() {
    bool wifiOk = connectWifi();
    bool ok = wifiOk && waitForClock() && downloadPage();
    // Off before using Bluetooth, as the two share a radio.
    disconnectWifi();
    return ok && sendToDisplay();
}

static void updateWithRetries() {
    for (int attempt = 1; attempt <= ATTEMPTS; attempt++) {
        Serial.printf("Update, attempt %d\n", attempt);
        if (update()) {
            Serial.println("Update complete");
            return;
        }
        if (attempt < ATTEMPTS) delay(RETRY_DELAY_MS);
    }
    Serial.println("Update failed; the previous page stays on screen");
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    notifications = xQueueCreate(8, sizeof(Notification));

    NimBLEDevice::init("");
    NimBLEDevice::setMTU(247);

    setenv("TZ", TZ_UK, 1);
    tzset();
    if (connectWifi()) waitForClock();
    disconnectWifi();
    Serial.println(clockIsSet() ? "Clock set" : "Clock not set yet");
}

void loop() {
    if (Serial.available() && Serial.read() == 'u') updateWithRetries();

    if (!clockIsSet()) {
        // No clock means no schedule, so keep trying.
        static uint32_t lastTry = 0;
        if (millis() - lastTry > RETRY_DELAY_MS) {
            lastTry = millis();
            if (connectWifi()) waitForClock();
            disconnectWifi();
        }
    } else {
        struct tm now;
        localTimeIn(TZ_UK, &now);
        int minute = now.tm_hour * 60 + now.tm_min;
        bool isSlot = now.tm_min % 30 == 0 && minute >= FIRST_UPDATE_MINUTE && minute <= LAST_UPDATE_MINUTE;
        if (isSlot && minute != lastSlot) {
            lastSlot = minute;
            updateWithRetries();
        }
    }
    delay(1000);
}
