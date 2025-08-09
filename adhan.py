# -*- coding: utf-8 -*-
"""
Adhan app — تحديث تلقائي من GitHub حسب version.txt،
mapping للمدن (lat/lon/tz/method)، offline fallback، GUI عربي مودرن (Light),
system tray, startup on Windows, single instance, play adhan 10s.
By SMRH
"""

import os
import sys
import json
import time
import threading
import requests
import socket
from datetime import datetime
from pathlib import Path

# GUI & audio
import pygame
import pystray
from PIL import Image, ImageDraw
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import tkinter.messagebox as messagebox

# Optional Windows reg access
try:
    import winreg
except Exception:
    winreg = None

# ------------- CONFIG: raw links on GitHub -------------
# ** عدّل هذه الروابط لو لزم **
RAW_VERSION = "https://raw.githubusercontent.com/SameerHegazy/adhanapp/main/version.txt"
RAW_CITIES   = "https://raw.githubusercontent.com/SameerHegazy/adhanapp/main/cities.json"
RAW_THEME    = "https://raw.githubusercontent.com/SameerHegazy/adhanapp/main/theme.json"
RAW_ADHAN_MP3= "https://raw.githubusercontent.com/SameerHegazy/adhanapp/main/adhan.mp3"
RAW_ADHAN_PY = "https://raw.githubusercontent.com/SameerHegazy/adhanapp/main/adhan.py"

FILES_TO_UPDATE = {
    "cities.json": RAW_CITIES,
    "theme.json": RAW_THEME,
    "adhan.mp3": RAW_ADHAN_MP3,
    "adhan.py": RAW_ADHAN_PY
}

REMOTE_VERSION_URL = RAW_VERSION
LOCAL_VERSION_FILE = "version.txt"

# API and intervals
ALADHAN_API = "http://api.aladhan.com/v1/timings"
UPDATE_INTERVAL = 1800   # 30 minutes
CHECK_INTERVAL = 5       # check prayer every 5 seconds
ADHAN_DURATION = 10      # seconds

# local config (per-device, not pushed to GitHub)
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "city_country": ["القاهرة", "Egypt"],  # [cityName, countryKeyFromCitiesJson]
    "volume": 80,
    "adhan_enabled": True,
    "auto_start": True
}

# local files
LOCAL_CITIES = "cities.json"
LOCAL_THEME  = "theme.json"
LOCAL_PRAYER_CACHE = "prayer_times_cache.json"

# single instance port
SINGLETON_PORT = 65432

# ---------------- utilities ----------------
def resource_path(p):
    """Path for PyInstaller compatibility."""
    try:
        base = sys._MEIPASS
    except Exception:
        base = os.path.abspath(".")
    return os.path.join(base, p)

def is_online(timeout=4):
    try:
        requests.head("https://www.google.com", timeout=timeout)
        return True
    except:
        return False

def safe_load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

def safe_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# ---------------- single instance ----------------
def check_already_running():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', SINGLETON_PORT))
        return s
    except socket.error:
        return None

# ---------------- config local ----------------
def load_config():
    cfg = DEFAULT_CONFIG.copy()
    doc = safe_load_json(CONFIG_FILE)
    if isinstance(doc, dict):
        cfg.update(doc)
    # ensure keys
    if "city_country" not in cfg:
        cfg["city_country"] = DEFAULT_CONFIG["city_country"]
    if "volume" not in cfg:
        cfg["volume"] = DEFAULT_CONFIG["volume"]
    if "adhan_enabled" not in cfg:
        cfg["adhan_enabled"] = DEFAULT_CONFIG["adhan_enabled"]
    return cfg

def save_config(cfg):
    safe_write_json(CONFIG_FILE, cfg)

# ---------------- version & update ----------------
def get_remote_version():
    try:
        r = requests.get(REMOTE_VERSION_URL, timeout=6)
        if r.status_code == 200:
            return r.text.strip()
    except:
        pass
    return None

def get_local_version():
    try:
        with open(LOCAL_VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except:
        return "0"

def download_file(url, dest):
    try:
        r = requests.get(url, stream=True, timeout=15)
        r.raise_for_status()
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
        os.replace(tmp, dest)
        return True
    except Exception as e:
        print(f"download_file error {url}: {e}")
        return False

def perform_update_if_needed_silent():
    """If remote version > local version, download files then restart."""
    try:
        remote = get_remote_version()
        local = get_local_version()
        if not remote:
            return False
        if remote == local:
            return False
        # download listed files (except adhan.py handled last)
        for name, url in FILES_TO_UPDATE.items():
            dest = os.path.abspath(name)
            ok = download_file(url, dest)
            if not ok:
                print(f"Failed to update {name}")
        # update version file locally
        with open(LOCAL_VERSION_FILE, "w", encoding="utf-8") as f:
            f.write(remote)
        # restart program to load new adhan.py
        python = sys.executable
        os.execv(python, [python] + sys.argv)
        return True
    except Exception as e:
        print("perform_update_if_needed_silent error:", e)
        return False

def ensure_local_data():
    """Try to download cities/theme/adhan.mp3 if online (non-forcing)."""
    if not is_online():
        return
    for name, url in FILES_TO_UPDATE.items():
        # we will download everything (including adhan.mp3) but adhan.py already handled in update flow
        if name == "adhan.py":
            continue
        try:
            download_file(url, os.path.abspath(name))
        except:
            pass

# ---------------- cities mapping & fetching ----------------
def get_city_mapping():
    doc = safe_load_json(LOCAL_CITIES)
    if not isinstance(doc, dict):
        return {}
    return doc

def fetch_prayer_times_for(city_name, country_key, mapping):
    entry = mapping.get(country_key, {}).get(city_name)
    if not entry:
        return None
    lat = entry.get("lat")
    lon = entry.get("lon")
    tz = entry.get("tz", "")
    method = entry.get("method", 2)
    params = {
        "latitude": lat,
        "longitude": lon,
        "method": method,
        "timezonestring": tz,
        "date": datetime.now().strftime("%d-%m-%Y")
    }
    try:
        r = requests.get(ALADHAN_API, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("code") == 200 and "data" in data:
            timings = data["data"]["timings"]
            safe_write_json(LOCAL_PRAYER_CACHE, {
                "fetched_at": datetime.now().isoformat(),
                "city": city_name,
                "country": country_key,
                "timings": timings
            })
            return timings
    except Exception as e:
        print("fetch_prayer_times_for error:", e)
    # fallback to cache
    cached = safe_load_json(LOCAL_PRAYER_CACHE)
    if cached and cached.get("city") == city_name:
        return cached.get("timings")
    return None

# ---------------- adhan player ----------------
class AdhanPlayer:
    def __init__(self, mp3_path="adhan.mp3", volume=0.8):
        pygame.mixer.init()
        self.mp3 = mp3_path if os.path.exists(mp3_path) else resource_path(mp3_path)
        self.volume = volume
        self._lock = threading.Lock()
        try:
            self.sound = pygame.mixer.Sound(self.mp3)
            self.sound.set_volume(self.volume)
        except Exception as e:
            print("AdhanPlayer load error:", e)
            self.sound = None

    def set_volume(self, v):
        self.volume = max(0.0, min(1.0, v))
        if self.sound:
            self.sound.set_volume(self.volume)

    def play(self, duration=ADHAN_DURATION):
        def _p():
            with self._lock:
                try:
                    if self.sound:
                        self.sound.play(-1)
                        time.sleep(duration)
                        pygame.mixer.stop()
                except Exception as e:
                    print("AdhanPlayer play error:", e)
        t = threading.Thread(target=_p, daemon=True)
        t.start()

    def stop(self):
        with self._lock:
            try:
                pygame.mixer.stop()
            except:
                pass

# ---------------- Main GUI app ----------------
class PrayerApp:
    def __init__(self):
        self.cfg = load_config()
        self.cities_map = get_city_mapping()
        self.ad_player = AdhanPlayer(mp3_path="adhan.mp3", volume=self.cfg.get("volume", 80)/100.0)
        self.timings = {}
        self.triggered = set()
        self.running = True
        self.sock = None

        # GUI
        self.root = tb.Window(themename="flatly")
        self.root.title("مواقيت الصلاة - By SMRH")
        self.root.geometry("480x580")
        try:
            ico = resource_path("icon.ico")
            if os.path.exists(ico):
                self.root.iconbitmap(ico)
        except:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        # load theme
        self.load_theme()

        # widgets
        self.create_widgets()

        # single instance
        self.sock = check_already_running()
        if not self.sock:
            messagebox.showwarning("تنبيه", "البرنامج مفتوح بالفعل!")
            sys.exit(0)

        # add to startup
        if self.cfg.get("auto_start", True):
            try:
                add_to_startup()
            except:
                pass

        # ensure local data (download mapping/theme/adhan.mp3 if online)
        ensure_local_data()

        # perform silent update if version changed (this may restart)
        try:
            perform_update_if_needed_silent()
        except:
            pass

        # initial fetch timings
        self.update_prayer_times()

        # start background loops
        self.start_background_loops()

    def load_theme(self):
        theme = safe_load_json(LOCAL_THEME) or {}
        self.font_family = theme.get("font", {}).get("family", "Tahoma")
        self.font_size = theme.get("font", {}).get("size", 12)
        self.colors = theme.get("colors", {
            "background": "#ffffff",
            "text": "#2c3e50",
            "highlight": "#007bff"
        })

    def create_widgets(self):
        frm = tb.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        tb.Label(frm, text="اختر دولتك:", font=(self.font_family, self.font_size+2, "bold")).pack(anchor="w", pady=(2,6))

        self.country_var = tb.StringVar()
        self.city_var = tb.StringVar()

        country_keys = list(self.cities_map.keys()) if self.cities_map else []
        if not country_keys:
            country_keys = ["Egypt"]

        self.country_combo = tb.Combobox(frm, values=country_keys, textvariable=self.country_var, state="readonly", bootstyle="info")
        self.country_combo.pack(fill="x")
        self.country_combo.bind("<<ComboboxSelected>>", self.on_country_changed)

        tb.Label(frm, text="المدينة:", font=(self.font_family, self.font_size)).pack(anchor="w", pady=(10,0))
        self.city_combo = tb.Combobox(frm, values=[], textvariable=self.city_var, state="readonly", bootstyle="info")
        self.city_combo.pack(fill="x")
        self.city_combo.bind("<<ComboboxSelected>>", self.on_city_changed)

        # restore selection
        sel_city, sel_country = self.cfg.get("city_country", DEFAULT_CONFIG["city_country"])
        if sel_country in country_keys and sel_city in (self.cities_map.get(sel_country, {}) if self.cities_map else {}):
            self.country_var.set(sel_country)
            self.populate_cities(sel_country)
            self.city_var.set(sel_city)
        else:
            self.country_var.set(country_keys[0])
            self.populate_cities(country_keys[0])
            first_city = list(self.cities_map.get(country_keys[0], {}).keys())[0] if self.cities_map else ""
            self.city_var.set(first_city)
            self.cfg["city_country"] = [first_city, country_keys[0]]
            save_config(self.cfg)

        tb.Button(frm, text="تحديث المواقيت الآن", command=self.update_prayer_times, bootstyle="success-outline").pack(fill="x", pady=8)

        tb.Label(frm, text="مواقيت الصلاة:", font=(self.font_family, self.font_size+1, "bold")).pack(anchor="w", pady=(8,4))
        self.times_box = tb.Text(frm, height=8, state="disabled", font=(self.font_family, self.font_size))
        self.times_box.pack(fill="both", pady=4)

        tb.Label(frm, text="مستوى الصوت:", font=(self.font_family, self.font_size)).pack(anchor="w", pady=(8,2))
        self.vol = tb.Scale(frm, from_=0, to=100, orient="horizontal", command=self.on_volume_change, bootstyle="info")
        self.vol.set(int(self.cfg.get("volume", 80)))
        self.vol.pack(fill="x")

        btns = tb.Frame(frm)
        btns.pack(fill="x", pady=8)
        tb.Button(btns, text="تشغيل الأذان", command=lambda: self.ad_player.play(), bootstyle="primary").pack(side="left", expand=True, fill="x", padx=4)
        tb.Button(btns, text="إيقاف الأذان", command=self.ad_player.stop, bootstyle="danger").pack(side="left", expand=True, fill="x", padx=4)

        self.log_box = tb.Text(frm, height=6, state="disabled", font=(self.font_family, 10))
        self.log_box.pack(fill="both", pady=6)

        tb.Label(frm, text="By SMRH", font=(self.font_family, 10, "italic")).pack(anchor="e")

    def populate_cities(self, country_key):
        cities = list(self.cities_map.get(country_key, {}).keys()) if self.cities_map else []
        self.city_combo.configure(values=cities)
        if cities:
            if self.city_var.get() not in cities:
                self.city_var.set(cities[0])

    def on_country_changed(self, e=None):
        c = self.country_var.get()
        self.populate_cities(c)
        self.cfg["city_country"] = [self.city_var.get(), c]
        save_config(self.cfg)
        self.update_prayer_times()

    def on_city_changed(self, e=None):
        c = self.country_var.get()
        self.cfg["city_country"] = [self.city_var.get(), c]
        save_config(self.cfg)
        self.update_prayer_times()

    def log(self, s):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ts}] {s}\n")
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def on_volume_change(self, val):
        vol = float(val) / 100.0
        self.ad_player.set_volume(vol)
        self.cfg["volume"] = int(float(val))
        save_config(self.cfg)

    def update_prayer_times(self):
        city, country = self.cfg.get("city_country", DEFAULT_CONFIG["city_country"])
        if is_online():
            self.log("جاري جلب مواقيت الصلاة من الإنترنت...")
            times = fetch_prayer_times_for(city, country, self.cities_map)
            if times:
                self.timings = times
                self.show_timings()
                self.log(f"تم تحديث المواقيت لـ {city} - {country}")
                self.triggered.clear()
                return
            else:
                self.log("فشل جلب المواقيت من API — المحاولة بالنسخة المحلية")
        # offline fallback
        cached = safe_load_json(LOCAL_PRAYER_CACHE)
        if cached and cached.get("city") == city:
            self.timings = cached.get("timings", {})
            self.show_timings()
            self.log("استخدام المواقيت المخزنة محليًا")
        else:
            self.timings = {}
            self.show_timings()
            self.log("لا توجد مواقيت متاحة حالياً")

    def show_timings(self):
        ar = {"Fajr":"الفجر","Dhuhr":"الظهر","Asr":"العصر","Maghrib":"المغرب","Isha":"العشاء","Sunrise":"الشروق"}
        self.times_box.configure(state="normal")
        self.times_box.delete("1.0", "end")
        for key in ["Fajr","Dhuhr","Asr","Maghrib","Isha"]:
            val = self.timings.get(key, "غير متوفر")
            self.times_box.insert("end", f"{ar.get(key,key)} : {val}\n")
        self.times_box.configure(state="disabled")

    def prayer_check_loop(self):
        while self.running:
            if not self.timings:
                time.sleep(CHECK_INTERVAL)
                continue
            now = datetime.now().strftime("%H:%M")
            for name, t in self.timings.items():
                if name.lower() == "sunrise":
                    continue
                t_clean = t.split(" ")[0].strip()
                if t_clean == now and name not in self.triggered:
                    self.triggered.add(name)
                    if self.cfg.get("adhan_enabled", True):
                        self.log(f"موعد صلاة {name} الآن — تشغيل الأذان لمدة {ADHAN_DURATION} ثانية")
                        self.ad_player.play(duration=ADHAN_DURATION)
            time.sleep(1)

    def periodic_update_loop(self):
        while self.running:
            try:
                perform_update_if_needed_silent()
                # ensure theme/cities/adhan.mp3 local copies exist
                ensure_local_data()
                # update prayer times
                self.update_prayer_times()
            except Exception as e:
                print("periodic_update_loop:", e)
            for _ in range(int(UPDATE_INTERVAL/5)):
                if not self.running:
                    break
                time.sleep(5)

    # tray icon
    def create_tray_icon(self):
        def _img():
            img = Image.new('RGB', (64,64), color=(52,152,219))
            d = ImageDraw.Draw(img)
            d.text((18,14), "ص", fill="white")
            return img
        menu = pystray.Menu(
            pystray.MenuItem("إظهار البرنامج", lambda icon, item: self.show_window()),
            pystray.MenuItem("تشغيل/إيقاف الأذان", lambda icon, item: self.toggle_adhan()),
            pystray.MenuItem("خروج", lambda icon, item: self.exit_app())
        )
        self.tray = pystray.Icon("adhan_app", _img(), "مواقيت الصلاة", menu=menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def minimize_to_tray(self):
        self.root.withdraw()
        if not hasattr(self, "tray") or self.tray is None:
            self.create_tray_icon()

    def show_window(self):
        try:
            self.root.deiconify()
            if hasattr(self, "tray") and self.tray:
                try:
                    self.tray.stop()
                except:
                    pass
                self.tray = None
        except:
            pass

    def toggle_adhan(self):
        self.cfg["adhan_enabled"] = not self.cfg.get("adhan_enabled", True)
        save_config(self.cfg)
        status = "مفعل" if self.cfg["adhan_enabled"] else "موقوف"
        self.log(f"تم تحويل الأذان إلى: {status}")

    def exit_app(self):
        self.running = False
        try:
            if hasattr(self, "tray") and self.tray:
                self.tray.stop()
        except:
            pass
        try:
            self.ad_player.stop()
        except:
            pass
        try:
            self.root.destroy()
        except:
            pass
        try:
            if self.sock:
                self.sock.close()
        except:
            pass
        sys.exit(0)

    def start_background_loops(self):
        t1 = threading.Thread(target=self.prayer_check_loop, daemon=True)
        t2 = threading.Thread(target=self.periodic_update_loop, daemon=True)
        t1.start(); t2.start()

    def run(self):
        # UI tick
        def ui_tick():
            self.show_timings()
            self.root.after(60000, ui_tick)
        self.root.after(1000, ui_tick)
        self.root.mainloop()

# --------------- Windows startup helper ---------------
def add_to_startup():
    if winreg is None:
        return
    try:
        exe_path = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(sys.argv[0])
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "AdhanAppBySMRH", 0, winreg.REG_SZ, exe_path)
        winreg.CloseKey(key)
    except Exception as e:
        print("add_to_startup error:", e)

# --------------- main ---------------
def main():
    # ensure local copies (cities/theme/adhan.mp3)
    ensure_local_data()
    # silent update check (may restart)
    try:
        perform_update_if_needed_silent()
    except:
        pass
    app = PrayerApp()
    app.run()

if __name__ == "__main__":
    # prevent multiple instances
    sock = check_already_running()
    if not sock:
        # if another instance is running, show warning and exit
        messagebox.showwarning("تنبيه", "البرنامج مفتوح بالفعل!")
        sys.exit(0)
    main()
