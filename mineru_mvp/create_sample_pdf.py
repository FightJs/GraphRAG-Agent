from fpdf import FPDF


def create_sample_pdf(output_path: str = "sample.pdf") -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "MinerU MVP Test Document", ln=True, align="C")
    pdf.ln(4)

    # Section 1
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "1. Introduction", ln=True)
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 7,
        "This document is generated for testing MinerU Cloud API parsing. "
        "It contains typical document elements: paragraphs, a data table, and a list. "
        "The goal is to verify that the MinerU pipeline correctly extracts structured content."
    )
    pdf.ln(4)

    # Section 2: Table
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "2. Sample Data Table", ln=True)

    headers = ["Product", "Q1 Sales", "Q2 Sales", "Growth"]
    col_w = [60, 35, 35, 35]

    pdf.set_fill_color(220, 220, 220)
    for h, w in zip(headers, col_w):
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(w, 8, h, border=1, fill=True)
    pdf.ln()

    rows = [
        ("Widget Alpha", "1,200", "1,540", "+28.3%"),
        ("Widget Beta",  "890",   "1,100", "+23.6%"),
        ("Widget Gamma", "2,300", "2,150", "-6.5%"),
        ("Widget Delta", "450",   "780",   "+73.3%"),
    ]
    for row in rows:
        for val, w in zip(row, col_w):
            pdf.set_font("Helvetica", size=10)
            pdf.cell(w, 8, val, border=1)
        pdf.ln()

    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 6, "Table 1: Quarterly sales comparison by product line", ln=True)
    pdf.ln(4)

    # Section 3: List
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "3. Key Findings", ln=True)
    pdf.set_font("Helvetica", size=11)
    points = [
        "Widget Delta showed the highest growth rate at 73.3%.",
        "Widget Gamma was the only product with declining sales.",
        "Overall portfolio grew by approximately 25% quarter-over-quarter.",
        "Continued investment in Delta and Alpha is recommended.",
    ]
    for pt in points:
        pdf.cell(8, 7, "-", ln=False)
        pdf.multi_cell(0, 7, pt)

    pdf.output(output_path)
    print(f"Created: {output_path}")


if __name__ == "__main__":
    create_sample_pdf()
