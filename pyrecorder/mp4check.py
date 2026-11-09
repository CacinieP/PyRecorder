"""Output validation: decide whether ffmpeg produced a playable MP4."""
import os


def mp4_has_moov(path):
    """Find a complete top-level moov box in a structurally complete MP4.

    A long recording's moov can itself exceed several MiB. Walk box headers
    and skip payloads instead of searching a fixed tail window, which also
    mistook the bytes "moov" inside media data for a completed trailer. This
    checks container completeness; it does not decode the media streams.
    """
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            offset = 0
            found_moov = False
            while offset < size:
                header = f.read(8)
                if len(header) != 8:
                    return False
                box_size = int.from_bytes(header[:4], "big")
                box_type = header[4:]
                header_size = 8
                if box_size == 1:  # 64-bit extended size
                    extended = f.read(8)
                    if len(extended) != 8:
                        return False
                    box_size = int.from_bytes(extended, "big")
                    header_size = 16
                elif box_size == 0:  # this box extends to EOF
                    box_size = size - offset
                if box_type == b"uuid":
                    header_size += 16  # required user-type identifier
                if box_size < header_size or box_size > size - offset:
                    return False
                found_moov = found_moov or box_type == b"moov"
                offset += box_size
                f.seek(offset)
            return found_moov
    except OSError:
        return False


def recording_succeeded(returncode, output_path):
    """Require a clean ffmpeg exit and a complete MP4 container.

    ffmpeg exits 0 after 'q' and 255 after SIGTERM; a negative code means it
    was killed and never finalised the container. The moov check catches the
    case where the exit code looks fine but the trailer is missing.
    """
    if returncode not in (0, 255):
        return False
    return mp4_has_moov(output_path)
