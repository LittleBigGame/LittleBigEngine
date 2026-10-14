import zlib

def inspect_app_tree():
    with open('scratch/app_tree_compare.png', 'rb') as f: data = f.read()
    idx = 8; idat = b''; w, h = 0, 0
    while idx < len(data):
        l = int.from_bytes(data[idx:idx+4], 'big'); c = data[idx+4:idx+8]
        if c == b'IHDR': w = int.from_bytes(data[idx+8:idx+12], 'big'); h = int.from_bytes(data[idx+12:idx+16], 'big')
        elif c == b'IDAT': idat += data[idx+8:idx+8+l]
        idx += 12 + l
    raw = zlib.decompress(idat); stride = 1 + w * 4

    for side, x_min, x_max in [("LEFT Full", 20, 420), ("RIGHT ToNodes", 450, 850)]:
        print(f"\n=== {side} ===")
        for x in range(x_min, x_max):
            ys = []
            for y in range(50, 450):
                r, g, b, _ = raw[y*stride + 1 + x*4 : y*stride + 1 + (x+1)*4]
                if r > 100 and g > 100 and b > 100 and abs(r-g) < 10 and abs(g-b) < 10:
                    ys.append(y)
            if len(ys) >= 10:
                print(f"X={x}: {len(ys)} pixels from Y={min(ys)} to Y={max(ys)}")

inspect_app_tree()
