import os
import sys
import json
import requests
import shutil
import time
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
import ttkbootstrap as ttk
from tkinter import messagebox
import pytz
import platform
import subprocess
import pygame
import pystray
from PIL import Image, ImageDraw

# ------------------ إعداد الروابط ------------------
GITHUB_BASE = "https://raw.githubusercontent.com/SameerHegazy/adhanapp/main"
FILES_TO_UPDATE = [
    "adhan.py",
    "cities.json",
    "theme.json",
    "adhan.mp3"
]
VERSION_URL = f"{GITHUB_BASE}/version.txt"
LOCAL_VERSION_FILE = "version.txt"

# ------------------ دوال التحديث ------------------
def get_remote_version():
    try:
        r = requests.get(VERSION_URL, timeout=5)
        if r.status_code == 200:
            return r.text.strip()
    except:
        return None
    return None

def get_local_version():
    if os.path.exists(LOCAL_VERSION_FILE):
        with open(LOCAL_VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "0"

def update_files():
    for file_name in FILES_TO_UPDATE:
        url = f"{GITHUB_BASE}/{file_name}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                with open(file_name, "wb") as f:
                    f.write(r.content)
        except Exception as e:
            print(f"فشل تحديث {file_name}: {e}")

def restart_program():
    python = sys.executable
    os.execl(python, python, *sys.argv)

def check_for_update():
    remote_ver = get_remote_version()
    local_ver = get_local_version()
    if remote_ver and remote_ver != local_ver:
        messagebox.showinfo("تحديث", "جارٍ التحديث...")
        update_files()
        with open(LOCAL_VERSION_FILE, "w", encoding="utf-8") as f:
            f.write(remote_ver)
        restart_program()

# ------------------ تحميل الإعدادات ------------------
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "city": "القاهرة",
    "volume": 100,
    "adhan_enabled": True
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

config = load_config()

# ------------------ إضافة للـ Startup ------------------
def add_to_startup():
    if platform.system() == "Windows":
        startup_path = os.path.join(os.getenv("APPDATA"), "Microsoft\\Windows\\Start Menu\\Programs\\Startup")
        script_path = os.path.abspath(sys.argv[0])
        shortcut_path = os.path.join(startup_path, "AdhanApp.lnk")
        try:
            import winshell
            from win32com.client import Dispatch
            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = script_path
            shortcut.WorkingDirectory = os.path.dirname(script_path)
            shortcut.IconLocation = script_path
            shortcut.save()
        except:
            pass

add_to_startup()

# ------------------ فحص التحديث أول ما يبدأ ------------------
check_for_update()
PRAYER_FILE = "prayer_times.json"
API_URL = "http://api.aladhan.com/v1/timingsByCity"

pygame.mixer.init()

# ------------------ جلب المواقيت ------------------
def fetch_prayer_times():
    try:
        params = {
            "city": config["city"],
            "country": "Egypt",
            "method": 5
        }
        r = requests.get(API_URL, params=params, timeout=5)
        if r.status_code == 200:
            data = r.json()
            times = data["data"]["timings"]
            with open(PRAYER_FILE, "w", encoding="utf-8") as f:
                json.dump(times, f, ensure_ascii=False, indent=4)
            return times
    except:
        pass
    if os.path.exists(PRAYER_FILE):
        with open(PRAYER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

prayer_times = fetch_prayer_times()

# ------------------ تشغيل الأذان ------------------
def play_adhan():
    try:
        pygame.mixer.music.load("adhan.mp3")
        pygame.mixer.music.set_volume(config["volume"] / 100)
        pygame.mixer.music.play()
        threading.Timer(10, stop_adhan).start()
    except Exception as e:
        print("خطأ تشغيل الأذان:", e)

def stop_adhan():
    pygame.mixer.music.stop()

# ------------------ مؤقت الصلاة ------------------
def check_prayers():
    now = datetime.now().strftime("%H:%M")
    for prayer, time_str in prayer_times.items():
        if now == time_str:
            if config["adhan_enabled"]:
                play_adhan()
    root.after(60000, check_prayers)  # كل دقيقة

# ------------------ تحديث المواقيت كل 30 دقيقة ------------------
def auto_update_prayers():
    global prayer_times
    prayer_times = fetch_prayer_times()
    root.after(1800000, auto_update_prayers)  # 30 دقيقة

# ------------------ واجهة المستخدم ------------------
root = ttk.Window(themename="flatly")
root.title("مواقيت الصلاة")
root.geometry("400x400")

ttk.Label(root, text="مواقيت الصلاة", font=("Cairo", 18, "bold")).pack(pady=10)

prayers_frame = ttk.Frame(root)
prayers_frame.pack(pady=5)

labels = {}
for prayer in ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]:
    lbl = ttk.Label(prayers_frame, text=f"{prayer}: --:--", font=("Cairo", 14))
    lbl.pack()
    labels[prayer] = lbl

def update_ui():
    for prayer, lbl in labels.items():
        if prayer in prayer_times:
            lbl.config(text=f"{prayer}: {prayer_times[prayer]}")
    root.after(60000, update_ui)

ttk.Label(root, text="By SMRH", font=("Cairo", 10)).pack(side="bottom", pady=5)

# ------------------ أيقونة الـ Tray ------------------
def create_image():
    img = Image.new("RGB", (64, 64), color=(0, 123, 255))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 64, 64), fill=(0, 123, 255))
    return img

def on_quit(icon, item):
    icon.stop()
    root.destroy()

def hide_window():
    root.withdraw()
    icon = pystray.Icon("adhan", create_image(), "مواقيت الصلاة", menu=pystray.Menu(
        pystray.MenuItem("إظهار", lambda : root.deiconify()),
        pystray.MenuItem("خروج", on_quit)
    ))
    icon.run()

root.protocol("WM_DELETE_WINDOW", hide_window)

# ------------------ تشغيل البرامج ------------------
update_ui()
check_prayers()
auto_update_prayers()
root.mainloop()
