"""
Raporlama servisi: Excel (.xlsx), CSV ve PDF dışa aktarma.
Filtrelenmiş arama sonuçları aynen dışa aktarılabilir
(arama parametresi export endpoint'lerine de iletilir).
"""
import csv
import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# Dışa aktarılan VM kolonları: (başlık, model alanı)
VM_COLUMNS = [
    ("VM Adı", "name"), ("VM ID", "vmid"), ("IP Adresleri", "ip_addresses"),
    ("MAC Adresleri", "mac_addresses"), ("İşletim Sistemi", "guest_os"),
    ("CPU", "cpu_count"), ("RAM (MB)", "ram_mb"), ("Disk (GB)", "disk_total_gb"),
    ("Güç Durumu", "power_state"), ("Host", "host_name"), ("Cluster", "cluster"),
    ("Datastore", "datastore"), ("VLAN", "vlans"), ("Ortam", "environment"),
    ("Sahip", "owner"), ("Tools/Agent", "tools_status"),
]

HOST_COLUMNS = [
    ("Host Adı", "name"), ("Yönetim IP", "mgmt_ip"), ("İşletim Sistemi", "os_version"),
    ("CPU Modeli", "cpu_model"), ("Çekirdek", "cpu_cores"),
    ("Toplam RAM (MB)", "ram_total_mb"), ("Kullanılan RAM (MB)", "ram_used_mb"),
    ("Disk (GB)", "disk_total_gb"), ("Cluster", "cluster"), ("Durum", "status"),
]


def _row_values(obj, columns):
    """Model nesnesinden kolon sırasına göre değerleri çıkar."""
    values = []
    for _, field in columns:
        if field == "host_name":  # VM -> ilişkili host adı
            values.append(obj.host_ref.name if getattr(obj, "host_ref", None) else "")
        else:
            v = getattr(obj, field, "")
            values.append("" if v is None else v)
    return values


def export_excel(items, columns, title="Envanter Raporu") -> bytes:
    """Biçimlendirilmiş Excel raporu üret."""
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]

    header_fill = PatternFill("solid", fgColor="1B3A57")
    header_font = Font(color="FFFFFF", bold=True)
    for col, (header, _) in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill, cell.font = header_fill, header_font
        cell.alignment = Alignment(horizontal="center")

    for row, item in enumerate(items, 2):
        for col, value in enumerate(_row_values(item, columns), 1):
            ws.cell(row=row, column=col, value=value)

    # Kolon genişliklerini içeriğe göre ayarla
    for col in range(1, len(columns) + 1):
        max_len = max((len(str(ws.cell(row=r, column=col).value or ""))
                       for r in range(1, min(ws.max_row, 200) + 1)), default=10)
        ws.column_dimensions[get_column_letter(col)].width = min(max_len + 3, 45)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_csv(items, columns) -> bytes:
    """UTF-8 BOM'lu CSV (Excel'de Türkçe karakter uyumu için)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow([h for h, _ in columns])
    for item in items:
        writer.writerow(_row_values(item, columns))
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def export_pdf(items, columns, title="Envanter Raporu") -> bytes:
    """Yatay A4 PDF tablo raporu."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph(title, styles["Title"]),
        Paragraph(f"Oluşturulma: {datetime.now():%d.%m.%Y %H:%M} — Kayıt: {len(items)}",
                  styles["Normal"]),
        Spacer(1, 6*mm),
    ]
    # PDF'te tüm kolonlar sığmaz; en önemli ilk 10 kolonu al
    cols = columns[:10]
    data = [[h for h, _ in cols]]
    for item in items:
        data.append([str(v)[:40] for v in _row_values(item, cols)])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A57")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5F8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(table)
    doc.build(elements)
    return buf.getvalue()
