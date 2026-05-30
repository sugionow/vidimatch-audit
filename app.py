import sys
import os
import re
import json
import asyncio
import traceback
import pandas as pd
from bs4 import BeautifulSoup
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTextEdit, QProgressBar, QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal
from playwright.async_api import async_playwright

APP_NAME = "VidiMatch Audit"
APP_TAGLINE = "Fast Duplicate Video Checker"


def detect_platform(url: str) -> str:
    url = str(url).lower()
    if "shopee" in url or "shp.ee" in url:
        return "shopee"
    if "tiktok" in url:
        return "tiktok"
    if "instagram" in url:
        return "instagram"
    if "facebook" in url or "fb.watch" in url:
        return "facebook"
    return "other"


def extract_video_code(url: str) -> str:
    url = str(url)
    patterns = [
        r"share-video/([^/?&]+)",
        r"/reel/([^/?&]+)",
        r"/p/([^/?&]+)",
        r"/stories/([^/?]+/[^/?]+)",
        r"videos/([^/?&]+)",
        r"video/([^/?&]+)",
        r"id\.shp\.ee/([^/?&]+)",
        r"shp\.ee/([^/?&]+)"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return url


def extract_thumbnail_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        return og_image.get("content")

    twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
    if twitter_image and twitter_image.get("content"):
        return twitter_image.get("content")

    return ""


def load_cookie_files(cookie_files):
    all_cookies = []

    for filename in cookie_files:
        try:
            with open(filename, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            for c in cookies:
                if "name" not in c or "value" not in c or "domain" not in c:
                    continue

                cookie = {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c["domain"],
                    "path": c.get("path", "/"),
                    "secure": c.get("secure", False),
                    "httpOnly": c.get("httpOnly", False)
                }

                if c.get("expirationDate"):
                    cookie["expires"] = int(c["expirationDate"])

                all_cookies.append(cookie)

        except Exception:
            pass

    return all_cookies


async def check_link_fast(page, url: str):
    result = {
        "video identity": "",
        "platform": detect_platform(url),
        "status": ""
    }

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)

        final_url = page.url
        html = await page.content()
        thumbnail = extract_thumbnail_from_html(html)
        video_code = extract_video_code(final_url)

        if thumbnail:
            result["video identity"] = thumbnail
        elif video_code:
            result["video identity"] = video_code
        else:
            result["video identity"] = final_url

        result["status"] = "berhasil"

    except Exception as e:
        result["video identity"] = extract_video_code(url)
        result["status"] = f"gagal: {str(e)}"

    return result


async def run_audit_async(master_file, cookie_files, log_callback, progress_callback):
    df = pd.read_excel(master_file)
    df.columns = [str(c).strip().lower() for c in df.columns]

    required_cols = ["no", "account", "link"]
    for col in required_cols:
        if col not in df.columns:
            raise Exception(f"Kolom wajib tidak ada: {col}. Master harus berisi: no, account, link")

    df = df[["no", "account", "link"]].copy()
    total = len(df)

    all_cookies = load_cookie_files(cookie_files)
    log_callback(f"Total data: {total}")
    log_callback(f"Total cookies: {len(all_cookies)}")

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768}
        )

        if all_cookies:
            await context.add_cookies(all_cookies)
            log_callback("Cookie berhasil dimasukkan")

        page = await context.new_page()

        for idx, row in df.iterrows():
            url = str(row["link"]).strip()
            log_callback(f"Cek {idx + 1}/{total}: {url}")

            if not url or url.lower() == "nan":
                results.append({
                    "video identity": "",
                    "platform": "",
                    "status": "link kosong"
                })
            else:
                data = await check_link_fast(page, url)
                results.append(data)

            progress_callback(int(((idx + 1) / total) * 100))
            await page.wait_for_timeout(500)

        await browser.close()

    hasil = pd.DataFrame(results)
    df["video identity"] = hasil["video identity"]
    df["platform"] = hasil["platform"]
    df["status"] = hasil["status"]

    first_seen = {}
    persamaan_video = []

    for idx, row in df.iterrows():
        identity = str(row["video identity"]).strip()

        if not identity or identity.lower() == "nan":
            persamaan_video.append("")
            continue

        if identity in first_seen:
            persamaan_video.append(f"Sama dengan baris {first_seen[identity]}")
        else:
            first_seen[identity] = idx + 2
            persamaan_video.append("")

    df["persamaan video"] = persamaan_video

    output_df = df[[
        "no",
        "account",
        "link",
        "video identity",
        "persamaan video",
        "platform",
        "status"
    ]]

    base_dir = os.path.dirname(master_file)
    output_file = os.path.join(base_dir, "hasil_vidimatch_audit.xlsx")
    output_df.to_excel(output_file, index=False)

    return output_file


class AuditWorker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished_ok = pyqtSignal(str)
    finished_error = pyqtSignal(str)

    def __init__(self, master_file, cookie_files):
        super().__init__()
        self.master_file = master_file
        self.cookie_files = cookie_files

    def run(self):
        try:
            output_file = asyncio.run(
                run_audit_async(
                    self.master_file,
                    self.cookie_files,
                    self.log.emit,
                    self.progress.emit
                )
            )
            self.finished_ok.emit(output_file)
        except Exception as e:
            error = str(e) + "\n\n" + traceback.format_exc()
            self.finished_error.emit(error)


class VidiMatchApp(QWidget):
    def __init__(self):
        super().__init__()
        self.master_file = ""
        self.cookie_files = []
        self.worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(APP_NAME)
        self.resize(760, 560)

        layout = QVBoxLayout()

        title = QLabel(f"<h1>{APP_NAME}</h1><p>{APP_TAGLINE}</p>")
        layout.addWidget(title)

        info = QLabel("Master Excel wajib kolom: <b>no | account | link</b>")
        layout.addWidget(info)

        row1 = QHBoxLayout()
        self.master_label = QLabel("Master Excel: belum dipilih")
        btn_master = QPushButton("Pilih Master Excel")
        btn_master.clicked.connect(self.choose_master)
        row1.addWidget(self.master_label)
        row1.addWidget(btn_master)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.cookie_label = QLabel("Cookie JSON: 0 file")
        btn_cookie = QPushButton("Tambah Cookie JSON")
        btn_cookie.clicked.connect(self.choose_cookies)
        row2.addWidget(self.cookie_label)
        row2.addWidget(btn_cookie)
        layout.addLayout(row2)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        self.start_button = QPushButton("Mulai Audit")
        self.start_button.clicked.connect(self.start_audit)
        layout.addWidget(self.start_button)

        self.setLayout(layout)

    def log(self, text):
        self.log_box.append(text)

    def choose_master(self):
        file, _ = QFileDialog.getOpenFileName(
            self,
            "Pilih Master Excel",
            "",
            "Excel Files (*.xlsx *.xls)"
        )
        if file:
            self.master_file = file
            self.master_label.setText(f"Master Excel: {file}")

    def choose_cookies(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Pilih Cookie JSON",
            "",
            "JSON Files (*.json)"
        )
        if files:
            self.cookie_files = files
            self.cookie_label.setText(f"Cookie JSON: {len(files)} file")

    def start_audit(self):
        if not self.master_file:
            QMessageBox.warning(self, "Peringatan", "Pilih master Excel dulu.")
            return

        self.start_button.setEnabled(False)
        self.progress.setValue(0)
        self.log_box.clear()
        self.log("Audit dimulai...")

        self.worker = AuditWorker(self.master_file, self.cookie_files)
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished_ok.connect(self.audit_success)
        self.worker.finished_error.connect(self.audit_error)
        self.worker.start()

    def audit_success(self, output_file):
        self.start_button.setEnabled(True)
        self.progress.setValue(100)
        self.log(f"Selesai. File hasil: {output_file}")
        QMessageBox.information(self, "Selesai", f"Audit selesai.\n\nFile hasil:\n{output_file}")

    def audit_error(self, error):
        self.start_button.setEnabled(True)
        self.log(error)
        QMessageBox.critical(self, "Error", error)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VidiMatchApp()
    window.show()
    sys.exit(app.exec())
