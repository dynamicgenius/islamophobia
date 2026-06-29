# Dependencies

## System Packages

```bash
sudo apt-get update
sudo apt-get install -y \
    python3 python3-pip \
    wkhtmltopdf \
    msmtp msmtp-mta \
    fonts-dejavu fonts-liberation \
    tesseract-ocr poppler-utils \
    sqlite3 git
```

## Python Packages

```bash
pip3 install \
    pandas numpy scikit-learn joblib \
    feedparser beautifulsoup4 requests \
    pdfplumber pytesseract Pillow \
    fpdf plotly lxml python-dotenv
```
