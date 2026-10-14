import zlib

def inspect_lines(png_path):
    with open(png_path, 'rb') as f:
        data = f.read()
    idx = 8; idat = b''; w, h = 0, 0
    while idx < len(data):
        length = int.from_bytes(data[idx:idx+4], 'big')
        ctype = data[idx+4:idx+8]
        if ctype == b'IHDR':
            w = int.from_bytes(data[idx+8:idx+12], 'big')
            h = int.from_bytes(data[idx+12:idx+16], 'big')
        elif ctype == b'IDAT':
            idat += data[idx+8:idx+8+length]
        idx += 12 + length
    raw = zlib.decompress(idat)
    stride = 1 + w * 4

    # Let's find where lines are drawn
    # Background color is roughly (21, 22, 26) or similar dark grey
    # Line color is (80, 85, 100) or similar
    print(f"Image {w}x{h}")

    # Let's check x positions for vertical lines on right side (ToNodes)
    # Right window starts around x=400
    for x in range(410, 480):
        vert_pixels = 0
        for y in range(50, 300):
            row = raw[y*stride + 1 : (y+1)*stride]
            r, g, b, a = row[x*4 : (x+1)*4]
            # If noticeably different from background
            if (r > 60 and g > 60 and b > 60) and not (r > 150 and g > 150 and b > 150): # not white text
                vert_pixels += 1
        if vert_pixels > 10:
            print(f"Column x={x} has {vert_pixels} line pixels")

inspect_lines('scratch/comparison.png')
