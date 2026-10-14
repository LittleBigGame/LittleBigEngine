import zlib

def inspect_png_lines(path, name):
    with open(path, 'rb') as f: data = f.read()
    idx = 8; idat = b''; w, h = 0, 0
    while idx < len(data):
        l = int.from_bytes(data[idx:idx+4], 'big'); c = data[idx+4:idx+8]
        if c == b'IHDR': w = int.from_bytes(data[idx+8:idx+12], 'big'); h = int.from_bytes(data[idx+12:idx+16], 'big')
        elif c == b'IDAT': idat += data[idx+8:idx+8+l]
        idx += 12 + l
    raw = zlib.decompress(idat); stride = 1 + w * 4
    print(f"\n=== {name} ({w}x{h}) ===")
    # Column of Game's trunk line is around x=50
    # Let's search x from 40 to 80
    for x in range(40, 80):
        vert = []
        for y in range(40, 200):
            px = tuple(raw[y*stride + 1 + x*4 : y*stride + 1 + (x+1)*4])
            if px[0] > 60 and px[0] < 120 and px[1] > 60 and px[1] < 120 and px[2] > 60 and px[2] < 120:
                vert.append(y)
        if len(vert) >= 5:
            print(f"X={x}: Y={min(vert)} to Y={max(vert)} (total {len(vert)} pixels)")

inspect_png_lines('scratch/single_full.png', 'single_full')
inspect_png_lines('scratch/single_tonodes.png', 'single_tonodes')
