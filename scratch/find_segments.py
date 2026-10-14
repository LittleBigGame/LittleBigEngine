import zlib

with open('scratch/comparison.png', 'rb') as f:
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

# Check background at x=200, y=200
bg = tuple(raw[200*stride + 1 + 200*4 : 200*stride + 1 + 201*4])
print("BG color:", bg)

# Left window (x: 20 to 380), Right window (x: 400 to 760)
for side_name, x_start, x_end in [("Left (Full)", 20, 380), ("Right (ToNodes)", 400, 760)]:
    print(f"\n--- {side_name} ---")
    # find vertical line columns
    for x in range(x_start, x_end):
        y_coords = []
        for y in range(40, 300):
            px = tuple(raw[y*stride + 1 + x*4 : y*stride + 1 + (x+1)*4])
            if px != bg and px[0] < 120 and px[1] < 120 and px[2] < 120:
                y_coords.append(y)
        if len(y_coords) >= 15:
            print(f"X={x}: continuous segments from Y={min(y_coords)} to Y={max(y_coords)} (count {len(y_coords)})")
