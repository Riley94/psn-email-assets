#!/usr/bin/env python3
"""Send psn_email.html as multipart HTML with inline CID images."""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path


# CID token in HTML (cid:<token>) -> image filename in the template directory
DEFAULT_INLINE_IMAGES: tuple[tuple[str, str], ...] = (
    ("psn_header_banner", "psn_header_banner.png"),
    ("psn_divider", "psn_divider.png"),
    ("psn_footer_graphic", "psn_footer.png"),
    ("loews_hotel", "loews.jpg"),
    ("royals_logo", "royals-logo.webp"),
    ("cme", "cme.png"),
)

DEFAULT_HTML = "psn_email.html"


def _guess_image_subtype(path: Path) -> str:
    ext = path.suffix.lower()
    mapping = {
        ".png": "png",
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".gif": "gif",
        ".webp": "webp",
    }
    try:
        return mapping[ext]
    except KeyError as exc:
        raise ValueError(f"Unsupported image type: {path}") from exc


def build_message(
    *,
    html_body: str,
    base_dir: Path,
    inline_images: tuple[tuple[str, str], ...],
    subject: str,
    from_addr: str,
    to_addrs: list[str],
    plain_fallback: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    plain = (
        plain_fallback
        or "PSN 18th Annual Conference — open this message in an HTML email client to see formatting and images."
    )
    msg.set_content(plain)
    msg.add_alternative(html_body, subtype="html")

    html_part = msg.get_body(preferencelist=("html",))
    if html_part is None:
        raise RuntimeError("Failed to locate HTML MIME part after add_alternative")

    for cid_token, filename in inline_images:
        img_path = base_dir / filename
        if not img_path.is_file():
            raise FileNotFoundError(f"Inline image not found: {img_path}")
        subtype = _guess_image_subtype(img_path)
        html_part.add_related(
            img_path.read_bytes(),
            maintype="image",
            subtype=subtype,
            cid=f"<{cid_token}>",
        )

    return msg


def _resolve_password(args: argparse.Namespace) -> str | None:
    if args.smtp_password:
        return args.smtp_password
    if args.smtp_password_file:
        return Path(args.smtp_password_file).read_text(encoding="utf-8").strip()
    return os.environ.get("SMTP_PASSWORD")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        description="Send psn_email.html with inline CID images via SMTP."
    )
    p.add_argument(
        "--template-dir",
        type=Path,
        default=script_dir,
        help="Directory containing the HTML template and image files (default: script directory)",
    )
    p.add_argument(
        "--html",
        type=str,
        default=DEFAULT_HTML,
        help=f"HTML filename inside template-dir (default: {DEFAULT_HTML})",
    )
    p.add_argument(
        "--subject",
        default="PSN 18th Annual Conference",
        help="Email subject",
    )
    p.add_argument(
        "--from",
        dest="from_addr",
        required=True,
        metavar="ADDRESS",
        help="From address (must be allowed by your SMTP provider)",
    )
    p.add_argument(
        "--to",
        dest="to_addrs",
        action="append",
        required=True,
        metavar="ADDRESS",
        help="Recipient (repeat for multiple)",
    )
    p.add_argument(
        "--smtp-host",
        help="SMTP server hostname (not needed with --dry-run)",
    )
    p.add_argument("--smtp-port", type=int, default=587, help="SMTP port (default: 587)")
    p.add_argument(
        "--smtp-user",
        help="SMTP auth username (default: same as --from)",
    )
    p.add_argument(
        "--smtp-password",
        help="SMTP password (avoid; prefer env SMTP_PASSWORD or --smtp-password-file)",
    )
    p.add_argument(
        "--smtp-password-file",
        help="Path to file containing SMTP password (trimmed)",
    )
    p.add_argument(
        "--no-tls",
        action="store_true",
        help="Do not use STARTTLS (e.g. local port 25 testing only)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the message and write it to --dry-run-out instead of sending",
    )
    p.add_argument(
        "--dry-run-out",
        type=Path,
        default=Path("psn_email_preview.eml"),
        help="Output path when using --dry-run (default: psn_email_preview.eml)",
    )
    ns = p.parse_args(argv)
    if not ns.dry_run and not ns.smtp_host:
        p.error("--smtp-host is required unless you pass --dry-run")
    return ns


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base_dir = args.template_dir.resolve()
    html_path = base_dir / args.html
    if not html_path.is_file():
        print(f"error: HTML template not found: {html_path}", file=sys.stderr)
        return 1

    try:
        msg = build_message(
            html_body=html_path.read_text(encoding="utf-8"),
            base_dir=base_dir,
            inline_images=DEFAULT_INLINE_IMAGES,
            subject=args.subject,
            from_addr=args.from_addr,
            to_addrs=args.to_addrs,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        out = args.dry_run_out
        out.write_bytes(msg.as_bytes())
        print(f"Wrote {out.resolve()} ({out.stat().st_size} bytes). Open in an email client to preview.")
        return 0

    password = _resolve_password(args)
    user = args.smtp_user or args.from_addr
    if password is None:
        print(
            "error: SMTP password not set. Use env SMTP_PASSWORD, "
            "--smtp-password-file, or --smtp-password.",
            file=sys.stderr,
        )
        return 1

    try:
        with smtplib.SMTP(args.smtp_host, args.smtp_port) as smtp:
            smtp.ehlo()
            if not args.no_tls:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"error: SMTP failed: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"error: network/socket: {e}", file=sys.stderr)
        return 1

    print(f"Sent to {', '.join(args.to_addrs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
