# backend/services/log_prettify.py

import asyncio
import tempfile
import warnings
from pathlib import Path
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

from backend.logging_config import get_logger

logger = get_logger(context="log_prettify")

# A month of transcripts converts in well under a second.
CONVERT_TIMEOUT = 20


async def strip_spans(html_string):
    # Called a line at a time, and a line that is only a DOS path or a URL makes
    # bs4 warn that it looks like a filename. It is always markup here.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MarkupResemblesLocatorWarning)
        soup = BeautifulSoup(html_string, 'html.parser')

    # Find all 'span' tags and unwrap them
    # Meaning keep the insides of the span tags but remove the tags themselves
    for span in soup.find_all('span'):
        span.unwrap()

    return soup.prettify()


async def strip_multiple_blank_lines(html):
    new_html = ""
    prev_line_len = 0

    for line in html.split("\n"):
        stripped = await strip_spans(line)
        if len(stripped) == 0 and prev_line_len == 0:
            pass
        else:
            if len(new_html):
                new_html += "\n"
            new_html += line

        prev_line_len = len(stripped)

    return new_html


async def ansi_to_html(log_ansi):
    # Resolve terminal-to-html relative to the project root
    project_root = Path(__file__).resolve().parent.parent.parent
    terminal_to_html = project_root / "terminal-to-html"

    with tempfile.TemporaryFile(mode='w+t') as fp:
        fp.write(log_ansi)
        fp.seek(0)  # Rewind to the beginning to read

        process = await asyncio.create_subprocess_exec(
            str(terminal_to_html),
            "-preview",
            stdin=fp,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                process.communicate(), timeout=CONVERT_TIMEOUT)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(f"terminal-to-html took over {CONVERT_TIMEOUT}s")

    # Its error text is not HTML; the caller falls back to escaping the input.
    if process.returncode != 0:
        raise RuntimeError(f"terminal-to-html exited {process.returncode}: "
                           f"{stderr_data.decode(errors='replace')[:200]}")
    return stdout_data.decode()
