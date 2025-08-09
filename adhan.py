# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import threading
import requests
from datetime import datetime
import pygame
import socket

import ttkbootstrap as tb
from ttkbootstrap.constants import *
import tkinter.messagebox as messagebox

CONFIG_FILE = "config.json"
API_URL = "http://api.aladhan.com/v1/timings"
UPDATE_INTERVAL = 1800  # 30 دقيقة
CHECK_INTERVAL = 5      # فحص الصلاة كل 5 ثواني
ADHAN_DURATION = 10     # مدة الأذان بالثواني

CITIES = {
    "الرياض": (24.7136, 46.6753),
    "دمياط": (31.4165, 31.8133),
    "القاهرة": (30.0444, 31.2357),
    "دبي": (25.276987, 55.296249),
    "الدوحة": (25.2854, 51.5310),
    "الكويت": (29.3759, 47.9774),
    "مسقط": (23.5859, 58.4059),
    "بغداد": (33.3152, 44.3661),
    "بيروت": (33.8938, 35.5018),
    "الخرطوم": (15.5007, 32.5599),
    "مكة": (21.3891, 39.8579),
    "المدينة المنورة": (24.5247, 39.5692),
    "جدة": (21.2854, 39.2376),
    "الجزائر": (36.7538, 3.0422),
    "تونس": (36.8065, 10.1815),
    "الدار البيضاء": (33.5731, -7.5898),
    "الخبر": (26.2172, 50.1971),
    "الأحساء": (25.3603, 49.5846),
    "إسطنبول": (41.0082, 28.9784),
    "دوزجا": (40.8438, 31.1565),    
}

TIMEZONE_MAPPING = {
    "الرياض": "Asia/Riyadh",
    "دمياط": "Africa/Cairo",
    "القاهرة": "Africa/Cairo",
    "دبي": "Asia/Dubai",
    "الدوحة": "Asia/Qatar",
    "الكويت": "Asia/Kuwait",
    "مسقط": "Asia/Muscat",
    "بغداد": "Asia/Baghdad",
    "بيروت": "Asia/Beirut",
    "الخرطوم": "Africa/Khartoum",
    "مكة": "Asia/Riyadh",
    "المدينة المنورة": "Asia/Riyadh",
    "جدة": "Asia/Riyadh",
    "الجزائر": "Africa/Algiers",
    "تونس": "Africa/Tunis",
    "الدار البيضاء": "Africa/Casablanca",
    "الخبر": "Asia/Riyadh",
    "الأحساء": "Asia/Riyadh",
    "إسطنبول": "Europe/Istanbul",
    "دوزجا": "Europe/Istanbul",
}

METHOD_MAPPING = {
    "الرياض": 4,
    "دمياط": 5,
    "القاهرة": 5,
    "دبي": 4,
    "الدوحة": 4,
    "الكويت": 4,
    "مسقط": 4,
    "بغداد": 5,
    "بيروت": 5,
    "الخرطوم": 5,
    "مكة": 4,
    "المدينة المنورة": 4,
    "جدة": 4,
    "الجزائر": 2,
    "تونس": 2,
    "الدار البيضاء": 2,
    "الخبر": 4,
    "الأحساء": 4,
    "إسطنبول": 13,
    "دوزجا": 13,
}

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def add_to_startup():
    try:
        import winreg
        exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
        winreg.SetValueEx(key, "PrayerAppBySMRH", 0, winreg.REG_SZ, exe_path)
        winreg.CloseKey(key)
    except Exception as e:
        print(f"خطأ في إضافة بدء التشغيل: {e}")

def check_already_running():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', 65432))
        return sock
    except socket.error:
        return None

class AdhanPlayer:
    def __init__(self):
        pygame.mixer.init()
        self.volume = 0.8
        self.sound = pygame.mixer.Sound(resource_path("adhan.mp3"))
        self.sound.set_volume(self.volume)
        self.is_playing = False

    def play(self):
        if not self.is_playing:
            self.sound.play(-1)
            self.is_playing = True

    def stop(self):
        if self.is_playing:
            pygame.mixer.stop()
            self.is_playing = False

    def set_volume(self, v):
        self.volume = max(0, min(1, v))
        self.sound.set_volume(self.volume)

class PrayerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("مواقيت الصلاة - By SMRH")
        self.root.geometry("440x570")
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        self.root.iconbitmap(resource_path("icon.ico")) if os.path.exists(resource_path("icon.ico")) else None

        self.style = tb.Style("flatly")
        self.style.configure('TLabel', font=('Tahoma', 12))
        self.style.configure('TButton', font=('Tahoma', 11))
        self.style.configure('TCombobox', font=('Tahoma', 12))
        self.style.configure('TScale', troughcolor='#b5d0e0')

        self.cfg = self.load_config()
        self.player = AdhanPlayer()
        self.timings = {}
        self.triggered_prayers = set()
        self.updater_thread = None
        self.checker_thread = None
        self.tray_icon = None
        self.is_running = True

        self.city_names = list(CITIES.keys())

        self.create_widgets()

        # ضبط المدينة المختارة من الملف config.json
        last_city = self.cfg.get("city", self.city_names[0] if self.city_names else "")
        if last_city in self.city_names:
            self.city_combo.set(last_city)
        else:
            self.city_combo.set(self.city_names[0] if self.city_names else "")

        self.update_timings()
        self.start_updater()
        self.start_checker()

        add_to_startup()

    def create_widgets(self):
        frame = tb.Frame(self.root, padding=10)
        frame.pack(fill='both', expand=True)

        tb.Label(frame, text="اختر مدينتك:", font=("Tahoma", 14, "bold")).pack(pady=8, anchor="w")

        self.city_var = tb.StringVar()
        self.city_combo = tb.Combobox(frame, textvariable=self.city_var, values=self.city_names, state="readonly", bootstyle="info")
        self.city_combo.pack(fill='x', pady=5)

        # إضافة حدث حفظ المدينة وتحديث التواقيت عند تغيير الاختيار
        self.city_combo.bind("<<ComboboxSelected>>", self.on_city_changed)

        tb.Button(frame, text="تحديث المواقيت الآن", command=self.update_timings, bootstyle="success").pack(pady=8, fill='x')

        tb.Label(frame, text="مواقيت الصلاة:", font=("Tahoma", 13, "bold")).pack(pady=8, anchor="w")

        self.times_text = tb.Text(frame, height=8, state="disabled", font=("Tahoma", 13))
        self.times_text.pack(fill='both', pady=5)

        tb.Label(frame, text="مستوى الصوت:", font=("Tahoma", 12)).pack(pady=5, anchor="w")

        self.vol_scale = tb.Scale(frame, from_=0, to=100, orient='horizontal', command=self.on_volume_changed, bootstyle="info")
        self.vol_scale.set(self.player.volume * 100)
        self.vol_scale.pack(fill='x')

        btn_frame = tb.Frame(frame)
        btn_frame.pack(pady=12, fill='x')

        tb.Button(btn_frame, text="تشغيل الأذان", command=self.player.play, bootstyle="primary").pack(side='left', expand=True, fill='x', padx=5)
        tb.Button(btn_frame, text="إيقاف الأذان", command=self.player.stop, bootstyle="danger").pack(side='left', expand=True, fill='x', padx=5)

        self.log_text = tb.Text(frame, height=6, state="disabled", font=("Tahoma", 11))
        self.log_text.pack(fill='both', pady=10)

        self.footer_label = tb.Label(frame, text="By SMRH", font=("Tahoma", 11, "italic"))
        self.footer_label.pack(pady=3, anchor="e")

    def on_city_changed(self, event):
        self.save_config()
        self.update_timings()

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert('end', f"[{timestamp}] {message}\n")
        self.log_text.configure(state="disabled")
        self.log_text.see('end')

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {}

    def save_config(self):
        self.cfg['city'] = self.city_var.get()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, ensure_ascii=False, indent=2)

    def update_timings(self):
        city = self.city_var.get()
        if city not in CITIES:
            self.log("المدينة غير موجودة")
            return

        lat, lng = CITIES[city]
        timezone = TIMEZONE_MAPPING.get(city, "UTC")
        method = METHOD_MAPPING.get(city, 2)

        params = {
            "latitude": lat,
            "longitude": lng,
            "method": method,
            "timezonestring": timezone,
            "date": datetime.now().strftime("%d-%m-%Y"),
        }

        try:
            resp = requests.get(API_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 200:
                self.timings = data["data"]["timings"]
                self.display_timings()
                self.log(f"تم تحديث المواقيت لـ {city}")
                self.triggered_prayers.clear()
            else:
                self.log("تعذر جلب بيانات المواقيت")
        except Exception as e:
            self.log(f"خطأ أثناء جلب المواقيت: {e}")

        self.save_config()  # حفظ المدينة بعد كل تحديث

    def display_timings(self):
        self.times_text.configure(state="normal")
        self.times_text.delete('1.0', 'end')
        for prayer in ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]:
            time_str = self.timings.get(prayer, "غير متوفر")
            arabic_names = {
                "Fajr": "الفجر",
                "Dhuhr": "الظهر",
                "Asr": "العصر",
                "Maghrib": "المغرب",
                "Isha": "العشاء"
            }
            display_name = arabic_names.get(prayer, prayer)
            self.times_text.insert('end', f"{display_name} : {time_str}\n")
        self.times_text.configure(state="disabled")

    def on_volume_changed(self, val):
        volume = float(val) / 100
        self.player.set_volume(volume)

    def check_prayer_time_loop(self):
        while self.is_running:
            if not self.timings:
                time.sleep(CHECK_INTERVAL)
                continue

            now = datetime.now()
            current_time_str = now.strftime("%H:%M")

            for prayer, t_str in self.timings.items():
                if prayer.lower() == "sunrise":
                    continue
                if t_str == current_time_str and prayer not in self.triggered_prayers:
                    self.triggered_prayers.add(prayer)
                    self.log(f"موعد صلاة {prayer} الآن، تشغيل الأذان لمدة {ADHAN_DURATION} ثانية")
                    self.player.play()
                    threading.Thread(target=self.stop_adhan_after_delay, daemon=True).start()

            time.sleep(CHECK_INTERVAL)

    def stop_adhan_after_delay(self):
        time.sleep(ADHAN_DURATION)
        self.player.stop()

    def update_timings_loop(self):
        while self.is_running:
            self.update_timings()
            for _ in range(int(UPDATE_INTERVAL / 5)):
                if not self.is_running:
                    break
                time.sleep(5)

    def minimize_to_tray(self):
        self.root.withdraw()
        if self.tray_icon is None:
            from PIL import Image, ImageDraw
            import pystray

            image = Image.new('RGB', (64, 64), color='#3498db')
            d = ImageDraw.Draw(image)
            d.text((20, 20), "ص", fill="white")
            menu = pystray.Menu(
                pystray.MenuItem("إظهار البرنامج", self.show_from_tray),
                pystray.MenuItem("خروج", self.exit_app)
            )
            self.tray_icon = pystray.Icon("adhan_app", image, "مواقيت الصلاة", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_from_tray(self):
        self.root.deiconify()
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None

    def exit_app(self):
        self.is_running = False
        self.player.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()

    def start_updater(self):
        self.updater_thread = threading.Thread(target=self.update_timings_loop, daemon=True)
        self.updater_thread.start()

    def start_checker(self):
        self.checker_thread = threading.Thread(target=self.check_prayer_time_loop, daemon=True)
        self.checker_thread.start()


if __name__ == "__main__":
    sock = check_already_running()
    if not sock:
        messagebox.showwarning("تنبيه", "البرنامج مفتوح بالفعل!")
        sys.exit()

    root = tb.Window(themename="flatly")
    app = PrayerApp(root)
    root.mainloop()
