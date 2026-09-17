"""Screenshot letter.html at desktop and phone width with Windows Chrome (headless).

    python3 -m lf.preview <customer> <send_date>

Writes issues/<send_date>/screens/desktop.png and mobile.png.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from lf.common import issue_dir

CHROME = [
    Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
]


def windows_path(path):
    return subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, check=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("customer")
    parser.add_argument("send_date")
    parser.add_argument("--file", default="letter.html", help="호 폴더 안의 HTML 파일 (템플릿 비교용)")
    args = parser.parse_args()

    browser = next((p for p in CHROME if p.exists()), None)
    if not browser:
        sys.exit("Chrome/Edge 를 찾지 못했습니다. letter.html 을 브라우저로 직접 열어 확인하세요.")

    folder = issue_dir(args.customer, args.send_date)
    screens = folder / "screens"
    screens.mkdir(exist_ok=True)
    page = "file:///" + windows_path(folder / args.file).replace("\\", "/")
    prefix = "" if args.file == "letter.html" else Path(args.file).stem.removeprefix("letter.") + "-"
    # Headless Chrome will not lay out narrower than 500px, so "mobile" is the narrowest it allows.
    for name, size in (("desktop", "720,2600"), ("mobile", "500,3000")):
        target = windows_path(screens / f"{prefix}{name}.png")
        subprocess.run(
            [str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--window-size={size}", f"--screenshot={target}", page],
            cwd="/mnt/c", capture_output=True, timeout=90,
        )
        print(screens / f"{prefix}{name}.png")


if __name__ == "__main__":
    main()
