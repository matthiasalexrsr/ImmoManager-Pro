"""Synthetic document fixtures, with real OOXML relationships and multiple PDF pages."""
import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.pdfgen import canvas


def rich_docx(paragraphs=420):
    output = io.BytesIO()
    image = io.BytesIO()
    Image.new("RGB", (96, 48), (40, 110, 170)).save(image, "PNG")
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
          'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
    picture = '<w:r><w:drawing><wp:inline><wp:extent cx="1828800" cy="914400"/><wp:docPr id="1" name="Prüfbild"/>' \
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>' \
        '<pic:nvPicPr><pic:cNvPr id="1" name="Prüfbild.png"/><pic:cNvPicPr/></pic:nvPicPr>' \
        '<pic:blipFill><a:blip r:embed="img1"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>' \
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1828800" cy="914400"/></a:xfrm>' \
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'
    first = '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Prüfdokument: Öl, Wärme, ÄÖÜ, ß, € und § 14</w:t></w:r></w:p>'
    first += '<w:p><w:commentRangeStart w:id="0"/><w:r><w:t>Dieser Text trägt einen Kommentar.</w:t></w:r>' \
        '<w:commentRangeEnd w:id="0"/><w:r><w:commentReference w:id="0"/></w:r>' \
        '<w:ins w:id="1" w:author="QA Prüfung" w:date="2026-10-16T00:00:00Z"><w:r><w:t> Nachverfolgte Einfügung.</w:t></w:r></w:ins>' \
        '<w:r><w:footnoteReference w:id="1"/></w:r></w:p>'
    first += '<w:p>' + picture + '</w:p>'
    first += '<w:p><w:fldSimple w:instr="TOC &quot;1-3&quot;"><w:r><w:t>Inhaltsverzeichnis (nach Aktualisierung)</w:t></w:r></w:fldSimple></w:p>'
    body = ''.join('<w:p><w:r><w:t>' + escape(f'{number:04d} – Mietverwaltung: Straße, Größe, Kosten 119,00 €; Zeile bleibt vollständig.')
                   + '</w:t></w:r></w:p>' for number in range(paragraphs))
    table = '<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/></w:tblPr><w:tblGrid><w:gridCol w:w="4500"/><w:gridCol w:w="4500"/></w:tblGrid>'
    for index in range(65):
        table += '<w:tr>' + ''.join('<w:tc><w:tcPr><w:tcW w:w="4500" w:type="dxa"/></w:tcPr><w:p><w:r><w:t>'
            + escape(value) + '</w:t></w:r></w:p></w:tc>' for value in (f'Raum {index:02d} – Küche', f'Beleg {index:02d}: 119,00 €')) + '</w:tr>'
    table += '</w:tbl>'
    section = '<w:sectPr><w:headerReference w:type="default" r:id="header1"/><w:footerReference w:type="default" r:id="footer1"/>' \
        '<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
    relationships = {"img1": ("image", "media/image1.png"), "header1": ("header", "header1.xml"),
        "footer1": ("footer", "footer1.xml"), "footnotes": ("footnotes", "footnotes.xml"),
        "comments": ("comments", "comments.xml"), "styles": ("styles", "styles.xml")}
    parts = {
        "word/document.xml": f'<w:document {ns}><w:body>{first}{body}{table}{section}</w:body></w:document>',
        "word/header1.xml": f'<w:hdr {ns}><w:p><w:r><w:t>ImmoManager – Kopfzeile § 14</w:t></w:r></w:p></w:hdr>',
        "word/footer1.xml": f'<w:ftr {ns}><w:p><w:r><w:t>Seite </w:t></w:r><w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple></w:p></w:ftr>',
        "word/footnotes.xml": f'<w:footnotes {ns}><w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
            '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
            '<w:footnote w:id="1"><w:p><w:r><w:t>Fußnote: Originalbezug vollständig erhalten.</w:t></w:r></w:p></w:footnote></w:footnotes>',
        "word/comments.xml": f'<w:comments {ns}><w:comment w:id="0" w:author="QA Prüfung" w:date="2026-10-16T00:00:00Z">'
            '<w:p><w:r><w:t>Kommentar mit Sonderzeichen: Wärme €.</w:t></w:r></w:p></w:comment></w:comments>',
        "word/styles.xml": f'<w:styles {ns}><w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
            '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
            '<w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style></w:styles>',
        "word/media/image1.png": image.getvalue(),
        "word/_rels/document.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + ''.join(f'<Relationship Id="{key}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" Target="{target}"/>'
                for key, (kind, target) in relationships.items()) + '</Relationships>',
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="root" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
    }
    overrides = {"document": "document.main", "header1": "header", "footer1": "footer", "footnotes": "footnotes", "comments": "comments", "styles": "styles"}
    parts["[Content_Types].xml"] = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' \
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' \
        '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>' \
        + ''.join(f'<Override PartName="/word/{name}.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"/>'
            for name, kind in overrides.items()) + '</Types>'
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        for name, value in parts.items():
            package.writestr(name, value)
    return output.getvalue()


def pdf_fixture():
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(595, 842))
    pdf.setTitle("VERTRAULICHE_METADATEN_4711")
    for index in range(4):
        pdf.setPageRotation(90 if index == 1 else 0)
        # ReportLab swaps the media dimensions for a quarter-turn. Keep text
        # inside that shorter unrotated height, otherwise the rotated-page
        # oracle is clipped before the PDF engine ever receives the fixture.
        top = 550 if index == 1 else 780
        pdf.drawString(30, top, f"SEITE_{index + 1}_ORAKEL: Waerme, Oel, 119.00 EUR")
        pdf.drawString(30, top - 50, "VERTRAULICH_4711")
        if index == 0:
            pdf.acroForm.textfield(name="Vermerk", x=30, y=650, width=240, height=24, value="Leerstand")
        pdf.showPage()
    pdf.save()
    return stream.getvalue()


def write_fixtures(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "Langdokument.docx").write_bytes(rich_docx())
    (directory / "Werkzeugpruefung.pdf").write_bytes(pdf_fixture())
    (directory / "Beschaedigt.docx").write_bytes(b"PK\x03\x04incomplete")
    photo = Image.new("RGB", (128, 96), (60, 130, 80))
    photo.save(directory / "Originalfoto.png")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    write_fixtures(parser.parse_args().directory)
