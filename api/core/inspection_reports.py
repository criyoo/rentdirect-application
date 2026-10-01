from __future__ import annotations

import textwrap
from datetime import datetime
from typing import Any

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN = 50
LINE_HEIGHT = 14
FONT_SIZE = 10
LINE_WIDTH = 95


def _ascii(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.strftime("%Y-%m-%d %H:%M UTC")
    text = str(value)
    return text.encode("ascii", "replace").decode("ascii")


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(item.replace("_", " ") for item in value) or "-"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str):
        return value.replace("_", " ") if value else "-"
    return str(value)


class _PdfBuilder:
    def __init__(self) -> None:
        self._pages: list[list[tuple[str, int]]] = []
        self._current: list[tuple[str, int]] = []
        self._max_lines = (PAGE_HEIGHT - 2 * MARGIN) // LINE_HEIGHT

    def add_line(self, text: str = "", *, bold: bool = False) -> None:
        wrapped = textwrap.wrap(text, LINE_WIDTH) or [""]
        for line in wrapped:
            if len(self._current) >= self._max_lines:
                self._pages.append(self._current)
                self._current = []
            self._current.append((line, 2 if bold else 1))

    def build(self) -> bytes:
        if self._current:
            self._pages.append(self._current)
            self._current = []
        if not self._pages:
            self._pages = [[]]

        objects: list[bytes] = []

        # 1: catalog, 2: pages, 3: F1 Helvetica, 4: F2 Helvetica-Bold
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(b"")  # placeholder for pages object
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

        page_object_ids: list[int] = []
        for page_lines in self._pages:
            page_id = len(objects) + 1
            content_id = page_id + 1
            page_object_ids.append(page_id)
            objects.append(
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                    f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                    f"/Contents {content_id} 0 R >>"
                ).encode("ascii")
            )
            commands = ["BT", f"/F1 {FONT_SIZE} Tf", f"{LINE_HEIGHT} TL", f"{MARGIN} {PAGE_HEIGHT - MARGIN} Td"]
            for line, font_id in page_lines:
                commands.append(f"/F{font_id} {FONT_SIZE} Tf")
                commands.append(f"({_escape_pdf_text(line)}) Tj")
                commands.append("T*")
            commands.append("ET")
            stream = "\n".join(commands).encode("ascii")
            objects.append(
                b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
            )

        kids = " ".join(f"{pid} 0 R" for pid in page_object_ids)
        objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>".encode("ascii")

        output = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, start=1):
            offsets.append(len(output))
            output += f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
        xref_position = len(output)
        output += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
        output += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            output += f"{offset:010d} 00000 n \n".encode("ascii")
        output += (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_position}\n%%EOF\n"
        ).encode("ascii")
        return bytes(output)


def build_inspection_report_pdf(inspection, checklist_schema: dict[str, Any]) -> bytes:
    listing = inspection.listing
    agent = inspection.agent
    responses = inspection.responses or {}
    analysis = inspection.analysis or {}

    builder = _PdfBuilder()
    builder.add_line("RentDirect Property Inspection Report", bold=True)
    builder.add_line("=" * 60)
    builder.add_line()

    builder.add_line("Property", bold=True)
    builder.add_line(f"Listing: {_ascii(listing.title)}")
    builder.add_line(
        "Address: "
        + _ascii(
            ", ".join(
                part
                for part in [listing.address, listing.city, listing.state]
                if part
            )
        )
    )
    landlord = listing.landlord
    builder.add_line(f"Landlord: {_ascii(getattr(landlord, 'name', '') or landlord.email)}")
    builder.add_line()

    builder.add_line("Inspector", bold=True)
    builder.add_line(f"Property Inspection Officer: {_ascii(agent.name or agent.email)}")
    builder.add_line(f"PIO email: {_ascii(agent.email)}")
    builder.add_line()

    builder.add_line("Inspection status", bold=True)
    builder.add_line(f"Status: {_ascii(inspection.get_status_display())}")
    builder.add_line(f"Overall status: {_ascii(inspection.overall_status).replace('_', ' ') or '-'}")
    builder.add_line(f"Claimed at: {_ascii(inspection.claimed_at)}")
    builder.add_line(f"Submitted at: {_ascii(inspection.submitted_at)}")
    builder.add_line(f"Signed off at: {_ascii(inspection.signed_off_at)}")
    builder.add_line(f"Earning amount: NGN {_ascii(inspection.earning_amount)}")
    builder.add_line(f"Payout status: {_ascii(inspection.get_payout_status_display())}")
    if inspection.payout_reference:
        builder.add_line(f"Payout reference: {_ascii(inspection.payout_reference)}")
    builder.add_line()

    if analysis:
        builder.add_line("Analysis", bold=True)
        builder.add_line(
            f"Completed items: {_ascii(analysis.get('completed_item_count', 0))} / "
            f"{_ascii(analysis.get('total_item_count', 0))}"
        )
        issues = analysis.get("issue_item_keys") or []
        builder.add_line(f"Issue items: {_ascii(', '.join(issues) if issues else 'None')}")
        flags = analysis.get("critical_red_flags") or []
        builder.add_line(f"Critical red flags: {_ascii(', '.join(flags) if flags else 'None observed')}")
        specialists = analysis.get("specialist_assessments") or []
        builder.add_line(
            f"Specialist assessments: {_ascii(', '.join(specialists) if specialists else 'None')}"
        )
        for key in (
            "documentation_assessment",
            "physical_condition",
            "utilities_assessment",
            "accessibility_assessment",
            "environmental_risk",
            "occupant_experience",
        ):
            if analysis.get(key):
                builder.add_line(f"{key.replace('_', ' ').capitalize()}: {_ascii(analysis[key])}")
        if analysis.get("final_recommendation"):
            builder.add_line(f"Final recommendation: {_ascii(analysis['final_recommendation'])}")
        builder.add_line()

    field_by_key = {
        field["key"]: field
        for section in checklist_schema.get("sections", [])
        for field in section.get("fields", [])
    }

    for section in checklist_schema.get("sections", []):
        builder.add_line(_ascii(section.get("title", section.get("key", ""))), bold=True)
        for field in section.get("fields", []):
            key = field["key"]
            value = responses.get(key)
            builder.add_line(f"{_ascii(field.get('label', key))}: {_ascii(_format_value(value))}")
        builder.add_line()

    extra_keys = sorted(set(responses.keys()) - set(field_by_key.keys()))
    if extra_keys:
        builder.add_line("Additional responses", bold=True)
        for key in extra_keys:
            builder.add_line(f"{_ascii(key)}: {_ascii(_format_value(responses[key]))}")
        builder.add_line()

    evidence = list(inspection.evidence_documents.all())
    builder.add_line("Evidence documents", bold=True)
    if evidence:
        for document in evidence:
            filename = getattr(getattr(document, "file", None), "name", "") or ""
            builder.add_line(f"- {_ascii(document.title or filename or document.id)}")
    else:
        builder.add_line("None uploaded.")
    builder.add_line()

    builder.add_line("Limitations & declaration", bold=True)
    for key in ("areas_not_inspected", "documents_not_provided", "limitations"):
        if responses.get(key):
            builder.add_line(f"{key.replace('_', ' ').capitalize()}: {_ascii(responses[key])}")
    declaration = responses.get("inspector_declaration")
    builder.add_line(
        "Inspector declaration: "
        + ("Confirmed by the inspecting property inspection officer." if declaration is True else "Not confirmed.")
    )

    return builder.build()
