"""
ECE 299 - Gawah Chong-Simard, Javan Hill

--------------------------------------------------------------------------------
GPIO 2: Rotary Encoder Pin B (Digital Input, IRQ on Rising/Falling edges)
GPIO 4: Rotary Encoder Pin A (Digital Input, IRQ on Rising/Falling edges)

GPIO 5: Rotary Encoder button (Digital Input, Internal Pull-Up, Active-Low)

GPIO 14: Mode Button (Digital Input, Internal Pull-Up, Active-Low)


GPIO 15: Alarm Button (Digital Input, Internal Pull-Up, Active-Low)
Display (SSD1309 OLED)

GPIO 16: Pico to Amp Channel

Protocol: Hardware SPI (Bus 0, Baudrate: 1,000,000)
GPIO 17: SPI CS (Chip Select)
GPIO 18: SPI SCK (Clock)
GPIO 19: SPI MOSI / SDA (Data Out)
GPIO 20: SPI DC (Data/Command)
GPIO 21: SPI RST (Reset)
FM Radio Module (e.g., RDA5807 or similar)

Protocol: Hardware I2C (Bus 1, Frequency: 200kHz)
Device Address: 0x10
GPIO 26: I2C SDA (Data)
GPIO 27: I2C SCL (Clock)

"""

from machine import Pin, I2C, SPI, PWM, Timer
import time
from ssd1309 import Display

# ==========================================================================
# HARDWARE CONFIGURATION
# ==========================================================================
SCREEN_WIDTH = 128
SCREEN_HEIGHT = 64

# ---- Rotary encoder ----
ENC_A = Pin(4, Pin.IN)
ENC_B = Pin(2, Pin.IN)
ENC_SW = Pin(5, Pin.IN, Pin.PULL_UP)      # active-LOW

# ---- Mode button ----
MODE_BTN = Pin(15, Pin.IN, Pin.PULL_UP)   # active-LOW

# ---- Alarm button (snooze / stop) ----
ALARM_BTN = Pin(14, Pin.IN, Pin.PULL_UP)  # active-LOW

# ---- OLED display (SPI0, 1 MHz). MISO is intentionally left unassigned:
#      the display is write-only and GPIO16 is needed for the buzzer, so we
#      must NOT let the SPI driver claim it as the default MISO pin. ----
SPI_ID = 0
_spi_sck = Pin(18)
_spi_mosi = Pin(19)
_spi_cs = Pin(17)
_spi_dc = Pin(20)
_spi_rst = Pin(21)

oled_spi = SPI(SPI_ID, baudrate=1_000_000, sck=_spi_sck, mosi=_spi_mosi)
oled = Display(spi=oled_spi, cs=_spi_cs, dc=_spi_dc, rst=_spi_rst,
                width=SCREEN_WIDTH, height=SCREEN_HEIGHT, flip=False)

# ---- Alarm buzzer using GPIO16 for PWM
BUZZER_PIN = 16
_buzzer_pwm = None


def _buzzer_on(freq_hz, duty):
    global _buzzer_pwm
    if _buzzer_pwm is None:
        _buzzer_pwm = PWM(Pin(BUZZER_PIN))
    _buzzer_pwm.freq(freq_hz)
    _buzzer_pwm.duty_u16(duty)


def _buzzer_off():
    global _buzzer_pwm
    if _buzzer_pwm is not None:
        _buzzer_pwm.deinit()
        _buzzer_pwm = None

# ---- FM radio module (I2C1, 200 kHz, address 0x10) ----
RADIO_I2C_BUS = 1
RADIO_I2C_ADDR = 0x10
_i2c_sda = Pin(26)
_i2c_scl = Pin(27)
radio_i2c = I2C(RADIO_I2C_BUS, scl=_i2c_scl, sda=_i2c_sda, freq=200_000)


# ==========================================================================
# RDA5807-TYPE FM TUNER DRIVER
# ==========================================================================
# Register bit layout below:

#   Reg 0x02 (CTRL)  hi byte: DHIZ(0x80) DMUTE(0x40) MONO(0x20) BASS(0x10) ..
#                    lo byte: .. RDS(0x08) NEW_METHOD(0x04) RESET(0x02) ENABLE(0x01)
#   Reg 0x03 (CHAN)  9-bit channel number <<6 | TUNE(0x10) | BAND | SPACING
#   Reg 0x04 (R4)    de-emphasis / soft-mute / AFC config bits
#   Reg 0x05 (VOL)   lo nibble = volume (0-15)
#
# Channel number uses 100 kHz spacing

class FMRadio:
    FREQ_MIN = 88.0
    FREQ_MAX = 108.0
    FREQ_BASE = 87.0

    def __init__(self, i2c, address=RADIO_I2C_ADDR):
        self.i2c = i2c
        self.address = address
        self.volume = 2
        self.frequency = 98.5
        self.chip_mute = False     # actual state we tell the chip
        self._needs_tune = True
        self.program()

    # ---- public setters (all clamp/validate, return True on success) ----
    def set_volume(self, vol):
        if not (0 <= vol <= 15):
            return False
        self.volume = vol
        return True

    def set_frequency(self, freq_mhz):
        freq_mhz = round(freq_mhz, 1)
        if not (self.FREQ_MIN <= freq_mhz <= self.FREQ_MAX):
            return False
        self.frequency = freq_mhz
        self._needs_tune = True
        return True

    def set_mute(self, mute):
        self.chip_mute = bool(mute)

    # ---- low level ----
    def _channel_number(self):
        return max(0, int(round((self.frequency - self.FREQ_BASE) * 10)))

    def program(self):
        """Push volume/frequency/mute state to the chip (sequential write,
        registers 0x02-0x05, 8 bytes total starting at 0x02)."""
        settings = bytearray(8)

        # ---- Register 0x02: CTRL ----
        settings[0] = 0xC0 if not self.chip_mute else 0x80   # DHIZ | (DMUTE)
        settings[1] = 0x0D                                    # RDS | NEW_METHOD | ENABLE

        # ---- Register 0x03: CHAN ----
        channel = self._channel_number()
        settings[2] = (channel >> 2) & 0xFF
        lsb = (channel & 0x03) << 6
        if self._needs_tune:
            lsb |= 0x10   # TUNE bit - one-shot, chip clears it once locked
            self._needs_tune = False
        settings[3] = lsb

        # ---- Register 0x04: R4 (default: 50us de-emphasis off / US region) ----
        settings[4] = 0x04
        settings[5] = 0x00

        # ---- Register 0x05: VOL ----
        settings[6] = 0x84
        settings[7] = 0x80 | (self.volume & 0x0F)

        try:
            self.i2c.writeto(self.address, settings)
        except OSError as e:
            print("Radio I2C write failed:", e)


# ==========================================================================
# SOFTWARE-DEBOUNCED BUTTON HELPER  (Mode button + encoder push-button)
# ==========================================================================
DEBOUNCE_MS = 50
LONG_PRESS_MS = 1000


class Button:
    def __init__(self, pin):
        self.pin = pin
        self._last_raw = 1
        self._last_change_ms = 0
        self.state = 1              # debounced state (1 = released, 0 = pressed)
        self.pressed_at = 0
        self.long_fired = False

    def update(self, now_ms):
        """Poll once per main-loop iteration. Returns (short_press, long_press)
        events that happened THIS call."""
        short_event = False
        long_event = False

        raw = self.pin.value()
        if raw != self._last_raw:
            self._last_change_ms = now_ms
            self._last_raw = raw

        if time.ticks_diff(now_ms, self._last_change_ms) > DEBOUNCE_MS:
            if raw != self.state:
                self.state = raw
                if raw == 0:                       # just pressed
                    self.pressed_at = now_ms
                    self.long_fired = False
                else:                               # just released
                    if not self.long_fired:
                        short_event = True

        if self.state == 0 and not self.long_fired:
            if time.ticks_diff(now_ms, self.pressed_at) >= LONG_PRESS_MS:
                self.long_fired = True
                long_event = True

        return short_event, long_event


mode_button = Button(MODE_BTN)
enc_button = Button(ENC_SW)
alarm_button = Button(ALARM_BTN)


# ==========================================================================
# ROTARY ENCODER (8-state transition table)
# ==========================================================================

ROTARY_POLL_MS = 1

_DIR_CW = 0x10
_DIR_CCW = 0x20
_DIR_MASK = 0x30
_STATE_MASK = 0x07

_R_START, _R_CW_1, _R_CW_2, _R_CW_3, _R_CCW_1, _R_CCW_2, _R_CCW_3, _R_ILLEGAL = range(8)

# Rows = current state, columns = pin reading (A<<1 | B) = 00, 01, 10, 11.
# A value with _DIR_CW/_DIR_CCW OR'd in means "a full step completed here".
_ROTARY_TABLE = (
    (_R_START,             _R_CCW_1, _R_CW_1,  _R_START),               # _R_START
    (_R_CW_2,              _R_START, _R_CW_1,  _R_START),               # _R_CW_1
    (_R_CW_2,              _R_CW_3,  _R_CW_1,  _R_START),               # _R_CW_2
    (_R_CW_2,              _R_CW_3,  _R_START, _R_START | _DIR_CW),     # _R_CW_3
    (_R_CCW_2,             _R_CCW_1, _R_START, _R_START),               # _R_CCW_1
    (_R_CCW_2,             _R_CCW_1, _R_CCW_3, _R_START),               # _R_CCW_2
    (_R_CCW_2,             _R_START, _R_CCW_3, _R_START | _DIR_CCW),    # _R_CCW_3
    (_R_START,             _R_START, _R_START, _R_START),               # _R_ILLEGAL
)

_encoder_state = _R_START
_encoder_delta = 0     # committed steps, consumed by the main loop


def _encoder_poll(timer):
    global _encoder_state, _encoder_delta
    curr = (ENC_A.value() << 1) | ENC_B.value()
    _encoder_state = _ROTARY_TABLE[_encoder_state & _STATE_MASK][curr]
    direction = _encoder_state & _DIR_MASK
    if direction == _DIR_CW:
        _encoder_delta += 1
    elif direction == _DIR_CCW:
        _encoder_delta -= 1


_encoder_timer = Timer(-1)
_encoder_timer.init(period=ROTARY_POLL_MS, mode=Timer.PERIODIC, callback=_encoder_poll, hard=True)


def take_encoder_delta():
    """Atomically read-and-clear the accumulated encoder motion since the
    last time the main loop consumed it. One physical detent = 1 (i.e. this
    is already in "steps", not raw edges -- no scaling needed by callers)."""
    global _encoder_delta
    d = _encoder_delta
    _encoder_delta = 0
    return d


# ==========================================================================
# UI FIELDS  (tap Mode button to cycle, turn encoder to adjust)
# ==========================================================================
(MODE_RADIO_VOL, MODE_TUNE, MODE_SET_HR, MODE_SET_MIN, MODE_FORMAT,
 MODE_ALM_HR, MODE_ALM_MIN, MODE_SNOOZE_LEN, MODE_ALM_TONE,
 MODE_ALM_VOL, MODE_TZ_OFFSET) = range(11)

MODE_NAMES = ("RADIO VOL", "TUNE", "SET HOUR", "SET MIN", "12H/24H",
              "ALARM HR", "ALARM MIN", "SNOOZE LEN", "ALARM TONE",
              "ALARM VOL", "TZ OFFSET")

# Second time-zone offset, in whole hours from the clock's own hour/minute

TZ_OFFSET_MIN = -12
TZ_OFFSET_MAX = 14

# Named FM presets -> shown on screen when the tuned frequency matches one.
# (Exceeds "display radio channel info": frequency + volume + channel name.)
RADIO_PRESETS = {
    88.5: "News88.5",
    91.3: "TheZone",
    98.5: "Ocean98.5",
    100.3: "TheQ",
    107.3: "KoolFM",
}

# User-selectable alarm tone patterns: (short display name, segments).
# Each segment is (frequency_hz, duration_ms); frequency_hz == 0 means
# silent for that slice. The pattern loops for as long as the alarm fires.

TONE_PATTERNS = (
    ("Beep",  ((1500, 500), (0, 500))),
    ("Siren", ((1200, 300), (2000, 300))),
    ("Chirp", ((2500, 100), (0, 100))),
    ("Sweep", ((1000, 150), (1400, 150), (1800, 150), (0, 150))),
)

# Alarm loudness floor/ceiling (PWM duty out of 65535). The floor keeps the
# alarm audible even at the lowest setting -- it can be made quieter, never
# silent, which is the whole point of separating it from the radio's volume.
ALARM_VOL_MAX = 9
ALARM_DUTY_FLOOR = 14000
ALARM_DUTY_CEIL = 32768


def format_clock(h, m, s, is_24h, with_seconds):
    """Render a time value. In 24h mode there's no AM/PM to disambiguate,
    so the caller is expected to also show the explicit 12H/24H tag
    (done in draw_screen) for an unambiguous indication of format."""
    if is_24h:
        return "%02d:%02d:%02d" % (h, m, s) if with_seconds else "%02d:%02d" % (h, m)
    hour12 = h % 12
    hour12 = 12 if hour12 == 0 else hour12
    ampm = "AM" if h < 12 else "PM"
    if with_seconds:
        return "%d:%02d:%02d %s" % (hour12, m, s, ampm)
    return "%02d:%02d %s" % (hour12, m, ampm)


class ClockRadio:
    def __init__(self, radio):
        self.radio = radio

        # ---- clock ----
        self.hour = 12
        self.minute = 0
        self.second = 0
        self.format_24h = False
        self._last_second_tick = time.ticks_ms()

        # ---- alarm ----
        self.alarm_hour = 7
        self.alarm_min = 0
        self.alarm_on = False
        self.alarm_firing = False
        self.snoozed = False
        self.snooze_len_min = 5           # user customizable, 1-30 min
        self._snooze_end_total_min = 0
        self.alarm_tone_index = 0         # index into TONE_PATTERNS
        self.alarm_vol = 6                # 0..ALARM_VOL_MAX
        self.tz_offset_hours = 8          # arbitrary nonzero default so the
                                           # second-zone readout is visibly
                                           # different out of the box

        # ---- user intent (separate from what we forced onto the chip) ----
        self.user_muted = False

        # ---- UI ----
        self.adjust_mode = MODE_RADIO_VOL
        self.dirty = True                 # display needs a redraw

    # ---------------------------------------------------------------
    # Encoder-driven adjustment of whichever field is currently selected
    # ---------------------------------------------------------------
    def apply_encoder_delta(self, delta):
        if delta == 0:
            return
        mode = self.adjust_mode

        if mode == MODE_RADIO_VOL:
            new_vol = max(0, min(15, self.radio.volume + delta))
            if self.radio.set_volume(new_vol):
                self.radio.program()

        elif mode == MODE_TUNE:
            new_freq = round(self.radio.frequency + delta * 0.1, 1)
            new_freq = max(self.radio.FREQ_MIN, min(self.radio.FREQ_MAX, new_freq))
            if self.radio.set_frequency(new_freq):
                self.radio.program()

        elif mode == MODE_SET_HR:
            self.hour = (self.hour + delta) % 24

        elif mode == MODE_SET_MIN:
            self.minute = (self.minute + delta) % 60

        elif mode == MODE_FORMAT:
            self.format_24h = not self.format_24h

        elif mode == MODE_ALM_HR:
            self.alarm_hour = (self.alarm_hour + delta) % 24

        elif mode == MODE_ALM_MIN:
            self.alarm_min = (self.alarm_min + delta) % 60

        elif mode == MODE_SNOOZE_LEN:
            self.snooze_len_min = max(1, min(30, self.snooze_len_min + delta))

        elif mode == MODE_ALM_TONE:
            self.alarm_tone_index = (self.alarm_tone_index + delta) % len(TONE_PATTERNS)

        elif mode == MODE_ALM_VOL:
            self.alarm_vol = max(0, min(ALARM_VOL_MAX, self.alarm_vol + delta))

        elif mode == MODE_TZ_OFFSET:
            self.tz_offset_hours = max(TZ_OFFSET_MIN, min(TZ_OFFSET_MAX, self.tz_offset_hours + delta))

        self.dirty = True

    def second_zone_time_str(self):
        """Local hour/minute shifted by tz_offset_hours, wrapping across
        midnight in either direction. Seconds/format follow the main clock
        so the two readouts are visually consistent."""
        total_min = (self.hour * 60 + self.minute + self.tz_offset_hours * 60) % (24 * 60)
        h2, m2 = divmod(total_min, 60)
        return format_clock(h2, m2, self.second, self.format_24h, False)

    def next_mode(self):
        self.adjust_mode = (self.adjust_mode + 1) % len(MODE_NAMES)
        self.dirty = True

    def toggle_alarm_armed(self):
        """Mode-button long press: master arm/disarm switch, works at any
        time. If the alarm happens to be ringing or snoozed when the user
        disarms it, silence it immediately too -- otherwise disarming
        would (confusingly) leave a currently-firing alarm still beeping."""
        self.alarm_on = not self.alarm_on
        if not self.alarm_on and (self.alarm_firing or self.snoozed):
            self.alarm_firing = False
            self.snoozed = False
            _buzzer_off()
            self._apply_chip_mute(forced_mute=False)
        self.dirty = True

    # ---------------------------------------------------------------
    # Mute handling: radio module gets muted either because the user
    # asked for it, or because the alarm/snooze logic forced it. We keep
    # those two reasons separate so turning the alarm off restores
    # whatever the user actually wanted.
    # ---------------------------------------------------------------
    def _apply_chip_mute(self, forced_mute):
        want_mute = forced_mute or self.user_muted
        if want_mute != self.radio.chip_mute:
            self.radio.set_mute(want_mute)
            self.radio.program()

    def toggle_user_mute(self):
        self.user_muted = not self.user_muted
        self._apply_chip_mute(forced_mute=self.alarm_firing)
        self.dirty = True

    # ---------------------------------------------------------------
    # Encoder button: jumps straight to the next named preset station
    # (wrapping around), without needing to enter TUNE mode and dial
    # through the band. Pure software, reuses RADIO_PRESETS -- no new I2C
    # reads, so it doesn't touch any of the tuning/audio code paths that
    # have needed hardware-debugging attention already.
    # ---------------------------------------------------------------
    def on_encoder_short_press(self):
        self.jump_to_next_preset()

    def jump_to_next_preset(self):
        presets = sorted(RADIO_PRESETS.keys())
        if not presets:
            return
        current = round(self.radio.frequency, 1)
        next_freq = presets[0]
        for f in presets:
            if f > current + 1e-6:
                next_freq = f
                break
        if self.radio.set_frequency(next_freq):
            self.radio.program()
        self.dirty = True

    # ---------------------------------------------------------------
    # Dedicated alarm button (GPIO14), labeled Snooze/Mute: short press =
    # snooze while the alarm is actually ringing, otherwise mute/unmute the
    # radio (same contextual behavior the encoder button used to have,
    # just relocated). Long press = stop today's alarm entirely; a no-op
    # unless the alarm is ringing or snoozed.
    # ---------------------------------------------------------------
    def on_alarm_button_short_press(self):
        if self.alarm_firing:
            self.alarm_firing = False
            self.snoozed = True
            _buzzer_off()
            total_min = self.hour * 60 + self.minute + self.snooze_len_min
            self._snooze_end_total_min = total_min % (24 * 60)
            self._apply_chip_mute(forced_mute=False)   # radio may play while snoozed
        else:
            self.toggle_user_mute()
        self.dirty = True

    def on_alarm_button_long_press(self):
        if not (self.alarm_firing or self.snoozed):
            return
        self.alarm_firing = False
        self.snoozed = False
        _buzzer_off()
        self._apply_chip_mute(forced_mute=False)
        self.dirty = True
        # alarm_on is left untouched -> alarm re-arms automatically for the
        # same alarm_hour:alarm_min the next day 

    # ---------------------------------------------------------------
    # Called ~50x/sec from the main loop.
    # ---------------------------------------------------------------
    def tick(self, now_ms):
        advanced = False
        while time.ticks_diff(now_ms, self._last_second_tick) >= 1000:
            self._last_second_tick = time.ticks_add(self._last_second_tick, 1000)
            self.second += 1
            advanced = True
            if self.second >= 60:
                self.second = 0
                self.minute += 1
                if self.minute >= 60:
                    self.minute = 0
                    self.hour = (self.hour + 1) % 24

                total_min = self.hour * 60 + self.minute
                if self.snoozed and total_min == self._snooze_end_total_min:
                    self.snoozed = False
                    self.alarm_firing = True
                    self._apply_chip_mute(forced_mute=True)

            if (self.alarm_on and not self.alarm_firing and not self.snoozed
                    and self.hour == self.alarm_hour
                    and self.minute == self.alarm_min and self.second == 0):
                self.alarm_firing = True
                self._apply_chip_mute(forced_mute=True)

        if self.alarm_firing:
            self._drive_buzzer(now_ms)

        if advanced:
            self.dirty = True

    def _alarm_duty(self):
        span = ALARM_DUTY_CEIL - ALARM_DUTY_FLOOR
        return ALARM_DUTY_FLOOR + int((self.alarm_vol / ALARM_VOL_MAX) * span)

    def _drive_buzzer(self, now_ms):
        """Step through the selected TONE_PATTERNS entry. Loudness comes
        from alarm_vol (see ALARM_DUTY_FLOOR/CEIL above), NOT the radio
        volume knob, so the alarm can never be accidentally silenced by
        turning the radio down."""
        name, segments = TONE_PATTERNS[self.alarm_tone_index]
        total = 0
        for _, dur in segments:
            total += dur
        t = now_ms % total
        acc = 0
        freq = 0
        for seg_freq, seg_dur in segments:
            acc += seg_dur
            if t < acc:
                freq = seg_freq
                break
        if freq:
            _buzzer_on(freq, self._alarm_duty())
        else:
            _buzzer_off()


# ==========================================================================
# DISPLAY  (128x64, 8x8 font -> 7 rows of 9 px pitch fit cleanly)
# Layout intentionally keeps every line comfortably under 16 characters
# (128 px / 8 px-per-glyph) so nothing gets clipped off the right edge.
# Exact pixel spacing is easy to restyle once you can see it on real
# hardware -- functionality (what's shown) is what matters here.
# ==========================================================================
def draw_screen(cr):
    oled.clear_buffers()

    # ---- Row 0 (y=0): alarm status ----
    if cr.alarm_firing:
        oled.draw_text8x8(0, 0, "!!! WAKE UP !!!")
    elif cr.snoozed:
        oled.draw_text8x8(0, 0, "SNOOZED (%dm)" % cr.snooze_len_min)
    else:
        alm_str = format_clock(cr.alarm_hour, cr.alarm_min, 0, cr.format_24h, False)
        oled.draw_text8x8(0, 0, "A:%s %s" % (alm_str, "ON" if cr.alarm_on else "OFF"))

    # ---- Row 1 (y=9): current time + explicit format tag ----
    time_str = format_clock(cr.hour, cr.minute, cr.second, cr.format_24h, True)
    fmt_label = "24H" if cr.format_24h else "12H"
    oled.draw_text8x8(0, 9, "%s %s" % (time_str, fmt_label))

    # ---- Row 2 (y=18): radio frequency + channel name ----
    freq = cr.radio.frequency
    name = RADIO_PRESETS.get(round(freq, 1), "FM Radio")
    oled.draw_text8x8(0, 18, "%5.1f %s" % (freq, name))

    # ---- Row 3 (y=27): radio volume + mute flag ----
    mute_flag = " M" if cr.radio.chip_mute else ""
    oled.draw_text8x8(0, 27, "Vol %2d/15%s" % (cr.radio.volume, mute_flag))

    # ---- Row 4 (y=36): radio volume bar (graphic only) ----
    bar_w = int((cr.radio.volume / 15) * 64)
    oled.draw_rectangle(0, 36, max(bar_w, 1), 4)

    # ---- Row 5 (y=45): which field the encoder currently edits ----
    oled.draw_text8x8(0, 45, "Adj:%s" % MODE_NAMES[cr.adjust_mode])

    # ---- Row 6 (y=54): live value/detail for fields not shown elsewhere.
    # Default (nothing else claiming this row) is a second time-zone
    # readout -- "Provides additional information such as time zone or
    # displays another time zone time" It's visible whenever the user isn't
    # actively adjusting one of the fields below that needs this row for
    # its own live value. ----
    mode = cr.adjust_mode
    if mode == MODE_SNOOZE_LEN:
        detail = "Snooze:%dm" % cr.snooze_len_min
    elif mode == MODE_ALM_TONE:
        detail = "Tone:%s" % TONE_PATTERNS[cr.alarm_tone_index][0]
    elif mode == MODE_ALM_VOL:
        detail = "AlarmVol:%d/%d" % (cr.alarm_vol, ALARM_VOL_MAX)
    elif mode == MODE_TZ_OFFSET:
        sign = "+" if cr.tz_offset_hours >= 0 else ""
        detail = "TZ Offset:%s%dh" % (sign, cr.tz_offset_hours)
    else:
        detail = "Zone2: %s" % cr.second_zone_time_str()
    if detail:
        oled.draw_text8x8(0, 54, detail)

    oled.present()


# ==========================================================================
# STARTUP
# ==========================================================================
fm_radio = FMRadio(radio_i2c, RADIO_I2C_ADDR)
fm_radio.set_frequency(98.5)
fm_radio.set_volume(2)
fm_radio.program()

clock = ClockRadio(fm_radio)

# ==========================================================================
# MAIN LOOP
# ==========================================================================
while True:
    now = time.ticks_ms()

    # ---- Mode button: short press = next field, long press = arm/disarm alarm ----
    short, long = mode_button.update(now)
    if short:
        clock.next_mode()
    if long:
        clock.toggle_alarm_armed()

    # ---- Encoder push-button: jump to the next preset station ----
    short, long = enc_button.update(now)
    if short:
        clock.on_encoder_short_press()
    # (long press on the encoder button is intentionally unused)

    # ---- Alarm button (Snooze/Mute): short = snooze if ringing else mute,
    #      long = stop today's alarm ----
    short, long = alarm_button.update(now)
    if short:
        clock.on_alarm_button_short_press()
    if long:
        clock.on_alarm_button_long_press()

    # ---- Rotary encoder rotation: applied directly, same as the reference ----
    delta = take_encoder_delta()
    if delta:
        clock.apply_encoder_delta(delta)

    # ---- Clock tick / alarm trigger / buzzer envelope ----
    clock.tick(now)

    # ---- Redraw only when something actually changed ----
    if clock.dirty:
        clock.dirty = False
        draw_screen(clock)

    time.sleep_ms(20)
    
