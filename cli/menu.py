"""
cli/menu.py
-----------
Interactive numbered test menu for the Raspbot RVFPM.
Run over SSH:  python -m cli.menu   (from repo root)
"""

import time
import sys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prompt(prompt: str = "Choice: ") -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "0"


def _print_header(title: str) -> None:
    print()
    print("=" * 40)
    print(f"  {title}")
    print("=" * 40)


def _get_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print("  Invalid – using default.")
        return default


# ---------------------------------------------------------------------------
# Sub-menus
# ---------------------------------------------------------------------------

def menu_motors(bot) -> None:
    MOVES = {
        "1":  ("Forward",                lambda: bot.motors.forward(speed)),
        "2":  ("Backward",               lambda: bot.motors.backward(speed)),
        "3":  ("Turn left",              lambda: bot.motors.turn_left(speed)),
        "4":  ("Turn right",             lambda: bot.motors.turn_right(speed)),
        "5":  ("Strafe left",            lambda: bot.motors.strafe_left(speed)),
        "6":  ("Strafe right",           lambda: bot.motors.strafe_right(speed)),
        "7":  ("Diagonal fwd-right",     lambda: bot.motors.diagonal_forward_right(speed)),
        "8":  ("Diagonal fwd-left",      lambda: bot.motors.diagonal_forward_left(speed)),
        "9":  ("Diagonal bwd-right",     lambda: bot.motors.diagonal_backward_right(speed)),
        "10": ("Diagonal bwd-left",      lambda: bot.motors.diagonal_backward_left(speed)),
        "11": ("Stop",                   lambda: bot.motors.stop()),
    }
    while True:
        _print_header("Motors")
        for k, (label, _) in MOVES.items():
            print(f"  {k:>2}. {label}")
        print("   0. Back")
        choice = _prompt()
        if choice == "0":
            bot.motors.stop()
            return
        if choice not in MOVES:
            print("  Unknown choice.")
            continue
        label, fn = MOVES[choice]
        if choice == "11":
            fn()
            print("  Stopped.")
            continue
        speed = _get_int("  Speed (0-255)", 150)
        duration = _get_int("  Duration seconds", 2)
        print(f"  {label} for {duration}s …")
        fn()
        time.sleep(duration)
        bot.motors.stop()
        print("  Stopped.")


def menu_servos(bot) -> None:
    while True:
        _print_header("Servos")
        print("  1. Pan angle")
        print("  2. Tilt angle")
        print("  3. Home (pan=90, tilt=25)")
        print("  0. Back")
        choice = _prompt()
        if choice == "0":
            return
        if choice == "1":
            angle = _get_int("  Pan angle (0-180)", 90)
            bot.servos.pan.set_angle(angle)
        elif choice == "2":
            angle = _get_int("  Tilt angle (0-90)", 45)
            bot.servos.tilt.set_angle(angle)
        elif choice == "3":
            bot.servos.home()
            print("  Homed.")
        else:
            print("  Unknown choice.")


def menu_sensors(bot) -> None:
    while True:
        _print_header("Sensors")
        print("  1. Distance – live (Ctrl+C to stop)")
        print("  2. Line tracker – live (Ctrl+C to stop)")
        print("  3. IR keycode – live (Ctrl+C to stop)")
        print("  0. Back")
        choice = _prompt()
        if choice == "0":
            return
        if choice == "1":
            print("  Reading distance … (Ctrl+C to stop)")
            with bot.ultrasonic:
                try:
                    while True:
                        print(f"\r  {bot.ultrasonic.read_cm():.1f} cm   ", end="", flush=True)
                        time.sleep(0.1)
                except KeyboardInterrupt:
                    print()
        elif choice == "2":
            print("  Reading line tracker … (Ctrl+C to stop)")
            try:
                while True:
                    state = bot.line_tracker.read()
                    print(f"\r  {state}   ", end="", flush=True)
                    time.sleep(0.05)
            except KeyboardInterrupt:
                print()
        elif choice == "3":
            print("  Reading IR codes … (Ctrl+C to stop)")
            with bot.ir:
                try:
                    while True:
                        code = bot.ir.read_keycode()
                        if code:
                            print(f"  Key: 0x{code:02X}")
                        time.sleep(0.05)
                except KeyboardInterrupt:
                    print()
        else:
            print("  Unknown choice.")


def menu_leds(bot) -> None:
    from raspbot import LedColor
    COLORS = {
        "1": ("Red",     LedColor.RED),
        "2": ("Green",   LedColor.GREEN),
        "3": ("Blue",    LedColor.BLUE),
        "4": ("White",   LedColor.WHITE),
        "5": ("Cyan",    LedColor.CYAN),
        "6": ("Magenta", LedColor.MAGENTA),
        "7": ("Yellow",  LedColor.YELLOW),
    }
    while True:
        _print_header("LEDs")
        print("  1. Set all (choose color)")
        print("  2. Effect: breathing")
        print("  3. Effect: river chase")
        print("  4. Off")
        print("  0. Back")
        choice = _prompt()
        if choice == "0":
            bot.leds.off_all()
            return
        if choice == "1":
            print("  Colors:")
            for k, (name, _) in COLORS.items():
                print(f"    {k}. {name}")
            c = _prompt("  Color choice: ")
            if c in COLORS:
                _, color = COLORS[c]
                bot.leds.set_all(color)
                print(f"  Set to {COLORS[c][0]}.")
        elif choice == "2":
            from raspbot import LedColor
            duration = _get_int("  Duration seconds", 5)
            print(f"  Breathing cyan for {duration}s …")
            bot.light_effects.start_breathing(LedColor.CYAN, speed=0.01)
            end = time.monotonic() + duration
            while time.monotonic() < end:
                bot.light_effects.update()
                time.sleep(0.001)
            bot.light_effects.stop()
            bot.leds.off_all()
        elif choice == "3":
            duration = _get_int("  Duration seconds", 5)
            print(f"  River chase for {duration}s …")
            bot.light_effects.start_river(speed=0.03)
            end = time.monotonic() + duration
            while time.monotonic() < end:
                bot.light_effects.update()
                time.sleep(0.001)
            bot.light_effects.stop()
            bot.leds.off_all()
        elif choice == "4":
            bot.leds.off_all()
            print("  LEDs off.")
        else:
            print("  Unknown choice.")


def menu_buzzer(bot) -> None:
    while True:
        _print_header("Buzzer")
        print("  1. Single beep")
        print("  2. Pattern (3 short beeps)")
        print("  0. Back")
        choice = _prompt()
        if choice == "0":
            return
        if choice == "1":
            duration = float(_get_int("  Beep duration ms", 300)) / 1000
            bot.buzzer.beep(duration)
            while bot.buzzer.is_active:
                bot.buzzer.update()
                time.sleep(0.001)
            print("  Done.")
        elif choice == "2":
            bot.buzzer.pattern(on_time=0.1, off_time=0.1, count=3)
            while bot.buzzer.is_active:
                bot.buzzer.update()
                time.sleep(0.001)
            print("  Done.")
        else:
            print("  Unknown choice.")


def menu_camera(bot) -> None:
    while True:
        _print_header("Camera")
        print("  1. Capture frame ? frame.jpg")
        print("  0. Back")
        choice = _prompt()
        if choice == "0":
            return
        if choice == "1":
            import cv2
            with bot.camera:
                frame = bot.camera.read_frame()
            if frame is not None:
                cv2.imwrite("frame.jpg", frame)
                print("  Saved: frame.jpg")
            else:
                print("  Failed to capture frame.")
        else:
            print("  Unknown choice.")


def menu_oled(bot) -> None:
    while True:
        _print_header("OLED Display")
        print("  1. Write two lines of text")
        print("  0. Back")
        choice = _prompt()
        if choice == "0":
            return
        if choice == "1":
            try:
                from raspbot.display.oled import OLEDDisplay
                line1 = input("  Line 1: ")
                line2 = input("  Line 2: ")
                with OLEDDisplay() as oled:
                    oled.clear()
                    oled.add_line(line1, line=1)
                    oled.add_line(line2, line=2)
                    oled.refresh()
                print("  Displayed.")
            except ImportError:
                print("  OLED extra not installed. Run: pip install 'raspbot[oled]'")
        else:
            print("  Unknown choice.")


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

MENU = {
    "1": ("Motors",   menu_motors),
    "2": ("Servos",   menu_servos),
    "3": ("Sensors",  menu_sensors),
    "4": ("LEDs",     menu_leds),
    "5": ("Buzzer",   menu_buzzer),
    "6": ("Camera",   menu_camera),
    "7": ("OLED",     menu_oled),
}


def main() -> None:
    from raspbot import Robot

    print()
    print("+--------------------------------------+")
    print("¦     Raspbot RVFPM – Test Menu        ¦")
    print("+--------------------------------------+")
    print("  Initialising robot …")

    with Robot() as bot:
        print("  Robot ready.\n")
        while True:
            _print_header("Main Menu")
            for k, (label, _) in MENU.items():
                print(f"  {k}. {label}")
            print("  0. Quit")
            choice = _prompt()
            if choice == "0":
                print("  Shutting down …")
                bot.motors.stop()
                bot.leds.off_all()
                break
            if choice in MENU:
                _, fn = MENU[choice]
                fn(bot)
            else:
                print("  Unknown choice.")


if __name__ == "__main__":
    main()
