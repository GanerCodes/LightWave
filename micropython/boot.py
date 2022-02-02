# TIMED_MODES:
#   DURATION (int)
#   MODE (bytearray)
#   LED_COUNT (int)
#   SHADERS (list)

import machine, time
time.sleep(0.2)
machine.freq(240000000)
import random, network, client, _thread, json, esp, os, gc
import usocket as socket
from ulab import numpy as np
from esp import neopixel_write
esp.osdebug(None)
gc.collect()

WEBSOCKET_SERVER = "wss://brynic.ganer.xyz:2096"

def boolStr(s):
    return s.strip().lower() in ('true', '1')

def safeRead(filename, strip = True):
    with open(filename, 'r') as f:
        contents = f.read()
        if strip:
            contents = contents.strip()
        return contents

def safeWrite(filename, content):
    with open(filename, 'w') as f: f.write(content)

if "LED_COUNT" in os.listdir():
    LED_COUNT = int(safeRead("LED_COUNT").strip())
else:
    safeWrite("LED_COUNT", '100')
    LED_COUNT = 100
PREVIOUS_LED_COUNT = LED_COUNT

if "REVERSE" in os.listdir():
    REVERSE = boolStr(safeRead("REVERSE"))
else:
    safeWrite("REVERSE", '0')
    REVERSE = False

def getRGBMode(mode):
    mode = mode.upper()
    return int(mode.index('R')), int(mode.index('G')), int(mode.index('B'))
if 'RGB_ORDER' in os.listdir():
    RGB_ORDER = safeRead("RGB_ORDER")
else:
    RGB_ORDER = "RGB"
    safeWrite("RGB_ORDER", RGB_ORDER)
OFFSET_R, OFFSET_G, OFFSET_B = getRGBMode(RGB_ORDER)

FF = const(255)
LOOP = True
MODES, SHADERS = [], []
RECTIME, TIMEDELTA = 0, 0

def processData(data, LED_COUNT):
    if 'LED_COUNT' in data:
        LED_COUNT = int(data['LED_COUNT'])
        safeWrite("LED_COUNT", str(LED_COUNT))
    for i, v in enumerate(data['modes']):
        bar = None
        if v['type'] == 'color':
            bar = bytearray([0x00, int(v['color'][0]), int(v['color'][1]), int(v['color'][2])])
        elif v['type'] == 'fade':
            tmp = []
            for x in v['colors']:
                for y in x:
                    tmp.append(int(y))
            sharpness = int(v['sharpness'] if 'sharpness' in v else 2)
            speed     = int(v['speed'    ] if 'speed'     in v else 4)
            bar = bytearray([0x01, speed, sharpness] + tmp + [0x00, 0x00, 0x00])
        elif v['type'] == 'rainbow':
            bar = bytearray([0x02, 255 - int(v['speed']), int(v['segCount']), int(v['direction'])])
            bar[1] = max(bar[1], 0x01)

        if bar:
            data['modes'][i] = [bar, np.array([], dtype = np.uint16)]
        else:
            data['modes'][i] = None

    inverse = np.array([], dtype = np.uint16)

    if 'segments' in data['mask']:
        for i in data['mask']['segments']:
            for o in data['mask']['segments'][i]:
                r = np.arange(o[0], o[1], dtype = np.uint16)
                data['modes'][int(i)][1] = np.concatenate((data['modes'][int(i)][1], r))
                inverse = np.concatenate((inverse, r))

    default = np.array([int(i) for i in range(LED_COUNT) if int(i) not in inverse], dtype = np.uint16)

    data['modes'][data['mask']['default']][1] = np.concatenate((data['modes'][data['mask']['default']][1], default))

    for i in data['modes']:
        i[1] = np.array([o for o in i[1] if o < LED_COUNT], dtype = np.uint16) #slow code but whatever, only happens when loading a mode
    
    if 'shaders' in data:
        shaders = data['shaders']
        for shader in shaders:
            if shader[0] == 'brightnessDiv':
                shader[1] = 11 - int(shader[1]) # Brightness comes in as as scale from 1 to 10
            elif shader[0] == 'rotate':
                shader[1] = int(shader[1]) * 1000
                shader[2] = int(shader[2])
    else:
        shaders = []
    
    return [list(filter(None, data['modes'])), LED_COUNT, shaders]

try:
    if "datafile" in os.listdir():
        dat = safeRead("datafile")
        JSON = json.loads(dat)
        tmp = processData(JSON, LED_COUNT)
        TIMED_MODES = [[-1, tmp[0],tmp[1],tmp[2]]]
        print("Loaded mode:", JSON)
    else:
        raise Exception()
except Exception as e:
    print("Could not load mode from file:", e)
    TIMED_MODES = [[-1, [
        [bytearray([0x00, 0x00, 0x00 , 0x00]), np.array([i for i in range(LED_COUNT) if i % 2     ], dtype = np.uint16)],
        [bytearray([0x00, 0x00, 0x255, 0x00]), np.array([i for i in range(LED_COUNT) if i % 2 == 0], dtype = np.uint16)]
    ], LED_COUNT, []]]

if 'UUID' not in os.listdir():
    UUID = hex(int(''.join(str(random.random())[2:] for i in range(3))))[2:10]
    safeWrite("UUID", UUID)
    print("Created UUID " + UUID)
else:
    UUID = safeRead("UUID")
    print("Using UUID: " + UUID)

@micropython.viper
def static_rgb(r: int, g: int, b: int, buf, offset: int):
    buf[offset + int(OFFSET_R)] = r
    buf[offset + int(OFFSET_G)] = g
    buf[offset + int(OFFSET_B)] = b

@micropython.viper
def static_rgb_default(r: int, g: int, b: int, buf, offset: int):
    buf[offset + 0] = r
    buf[offset + 1] = g
    buf[offset + 2] = b

@micropython.viper
def color_fade(r1 : int, g1 : int, b1: int, r2: int, g2: int, b2: int, proportion : int, buf, offset: int):
    buf[offset + int(OFFSET_R)] = r1 + (proportion * (r2 - r1)) // 255
    buf[offset + int(OFFSET_G)] = g1 + (proportion * (g2 - g1)) // 255
    buf[offset + int(OFFSET_B)] = b1 + (proportion * (b2 - b1)) // 255

@micropython.viper
def static_hsv(h : int, s : int, v : int, buf, offset : int):
    if s == 0:
        buf[offset + int(OFFSET_R)] = v
        buf[offset + int(OFFSET_G)] = v
        buf[offset + int(OFFSET_B)] = v
        return
    region = int(h // 43)
    remainder = (h - (region * 43)) * 6

    p = (v * (FF - s)) >> 8
    q = (v * (FF - ((s * remainder) >> 8))) >> 8
    t = (v * (FF - ((s * (FF - remainder)) >> 8))) >> 8
    if region == 0:
        buf[offset + int(OFFSET_R)] = v
        buf[offset + int(OFFSET_G)] = t
        buf[offset + int(OFFSET_B)] = p
    elif region == 1:
        buf[offset + int(OFFSET_R)] = q
        buf[offset + int(OFFSET_G)] = v
        buf[offset + int(OFFSET_B)] = p
    elif region == 2:
        buf[offset + int(OFFSET_R)] = p
        buf[offset + int(OFFSET_G)] = v
        buf[offset + int(OFFSET_B)] = t
    elif region == 3:
        buf[offset + int(OFFSET_R)] = p
        buf[offset + int(OFFSET_G)] = q
        buf[offset + int(OFFSET_B)] = v
    elif region == 4:
        buf[offset + int(OFFSET_R)] = t
        buf[offset + int(OFFSET_G)] = p
        buf[offset + int(OFFSET_B)] = v
    elif region == 5:
        buf[offset + int(OFFSET_R)] = v
        buf[offset + int(OFFSET_G)] = p
        buf[offset + int(OFFSET_B)] = q

@micropython.viper
def divideBrightness(buf, div: int, LED_COUNT: int):
    for i in range(LED_COUNT * int(3)):
        buf[i] = int(buf[i]) // div

@micropython.viper
def rotateLEDs(buf, newBuf, splitLoc: int, LED_COUNT: int, proportion: int):
    m = int(LED_COUNT * int(3))
    if proportion == 0:
        for i in range(m):
            newBuf[i] = buf[(i + splitLoc) % m]
    else:
        for i in range(m):
            s = int(buf[(i + splitLoc) % m])
            e = int(buf[(i + splitLoc + 3) % m])
            newBuf[i] = s + (proportion * (e - s)) // int(255)

@micropython.viper
def lightInterface(buf, l : int, TIMER : int):
    for i in range(int(len(MODES))):
        idx = MODES[i]
        j = ptr8(idx[0])
        k = ptr16(idx[1])
        if j[0] == 0: #Static
            for offset in range(int(len(idx[1]))):
                static_rgb(j[1], j[2], j[3], buf, k[offset] * 3)
        elif j[0] == 1: #Fade
            length = int(len(idx[0]))
            for offset in range(int(len(idx[1]))):
                static_rgb(j[length - 3], j[length - 2], j[length - 1], buf, k[offset] * 3)
        elif j[0] == 2: #Rainbow
            itt = int(len(idx[1]))
            for offset in range(itt):
                j1 = int(j[1])
                j2 = int(j[2])
                index = int(offset)
                if j[3] == 1:
                    index = int(itt - 1 - index)
                static_hsv(((0xFF * TIMER) // (100 * j1) + (k[offset] * j2 * 0xFF) // l) % 0xFF, 0xFF, 0xFF, buf, k[index] * 3)

def lightThread():
    global LOOP, LED_COUNT, PREVIOUS_LED_COUNT, TIMEDELTA, TIMED_MODES, SHADERS, MODES

    pin = machine.Pin(23)
    pin.init(pin.OUT)
    
    count = 3 * LED_COUNT
    buf = bytearray(count)
    buf_new = bytearray(count)
    buf_final = bytearray(count)

    TIMER_MODULO = 2 ** 32
    NEXT_FPS_TIME, COUNTER = time.time_ns() / 1_000_000 + (FPS_DISPLAY_DELTA := 20_000), 0
    
    while LOOP:
        ct_tmp = time.time_ns() / 1_000_000
        TIMER = (int(ct_tmp) + TIMEDELTA) % TIMER_MODULO

        COUNTER += 1
        if ct_tmp >= NEXT_FPS_TIME:
            a = gc.mem_free()
            b = gc.mem_alloc()
            print("FPS:", COUNTER / (FPS_DISPLAY_DELTA / 1_000), "\tUSED MEM:", str(b), "/", str(a + b), "\tRUNTIME:", str(ct_tmp))
            
            COUNTER = 0
            NEXT_FPS_TIME = ct_tmp + FPS_DISPLAY_DELTA

        while len(TIMED_MODES) > 1 and ct_tmp > TIMED_MODES[0][0]:
            TIMED_MODES.pop(0)
        MODES     = TIMED_MODES[0][1]
        LED_COUNT = TIMED_MODES[0][2]
        SHADERS   = TIMED_MODES[0][3]

        if LED_COUNT != PREVIOUS_LED_COUNT:
            del buf
            count = 3 * LED_COUNT
            buf = bytearray(count)
            buf_new = bytearray(count)
            buf_final = bytearray(count)
            PREVIOUS_LED_COUNT = LED_COUNT

        for b in MODES:
            b = b[0]
            if b[0] == 1: #Fade
                length = len(b) - 1 #minus 1 for easy color set code
                count = (length - 5) // 3 #length -5 for id, speed, sharpness, buffer; all minus 1 because line above

                v = b[1] * float(ct_tmp + TIMEDELTA) / 5000
                dec = (v - int(v)) ** (b[2] / 2.0) #Decimal ^ (sharpness / 2.0)
                c1 = int(v) % count
                c2 = 3 + 3 * ((c1 + 1) % count)
                c1 = 3 + 3 * c1

                b[length - 2] = int(b[c1    ] + dec * (b[c2    ] - b[c1    ]))
                b[length - 1] = int(b[c1 + 1] + dec * (b[c2 + 1] - b[c1 + 1]))
                b[length    ] = int(b[c1 + 2] + dec * (b[c2 + 2] - b[c1 + 2]))
        
        lightInterface(buf, LED_COUNT, TIMER)
        
        tradeBuf = False
        for shader in SHADERS:
            if shader[0] == 'brightnessDiv': #brightness div
                divideBrightness(buf, shader[1], LED_COUNT)
            if shader[0] == 'rotate': #duration, shift number
                tradeBuf = True
                if shader[2] == 1:
                    rotateLEDs(buf, buf_new, 3 * shader[2] * (int(LED_COUNT * TIMER / shader[1]) % LED_COUNT), LED_COUNT, int(255 * TIMER * LED_COUNT / shader[1]) % 255)
                else:
                    rotateLEDs(buf, buf_new, 3 * shader[2] * (int(LED_COUNT * TIMER / shader[1]) % LED_COUNT), LED_COUNT, 0)
        finalBufRef = buf_new if tradeBuf else buf
        
        if REVERSE:
            for i in range(LED_COUNT):
                index = 3 * i
                buf_final[index    ] = finalBufRef[-index - 3]
                buf_final[index + 1] = finalBufRef[-index - 2]
                buf_final[index + 2] = finalBufRef[-index - 1]
            finalBufRef = buf_final
        
        neopixel_write(pin, finalBufRef, 1)

_thread.start_new_thread(lightThread, ())

try:
    assert (credentials := 'credentials') in os.listdir(), "Could not find wifi config."
    
    time.sleep(0.5)
    
    router_username, router_password, token = map(str.strip, safeRead(credentials).split('\n')[:3])
    # print(router_username, router_password, token)
    print("SSID:", router_username)
    print("Router Password:", router_password)
    print("Token:", token)
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)
    sta_if.connect(router_username, router_password)
    r = 30
    for i in range(r):
        if sta_if.isconnected():
            break
        time.sleep(1)
        print('Failed to connect to network [' + str(i + 1) + '/' + str(r) + ']')
    else:
        sta_if.active(False)
        raise Exception("Could not connect to network.")
    print("Connected to Router!")
except Exception as e: # This entire section is dumb but it works
    print(e)

    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid = "Brynic LED Controller", password = "")

    while ap.active() == False: pass

    print('Created AP:', ap.ifconfig())

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 80))
    s.listen(5)

    headers = """HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"""
    pageHTML = safeRead('index.html')

    while True:
        conn, addr = s.accept()
        print("Got a connection from", addr)
        time.sleep(0.05)
        while True:
            try:
                c = str(conn.recv(1024))
                print("GOT C:", c)
                try:
                    if ' ^Z_ ' in c:
                        try:
                            c = json.loads(c.split(' ^Z_ ')[1].strip())
                            safeWrite(credentials, c['SSID']+'\n'+c['PASS']+'\n'+c['TOKE'])
                        except Exception as e:
                            print("Error decoding request JSON:", e)
                            continue
                        print("Got new credentials, resetting.")
                        machine.reset()
                    else:
                        print("Delimiter not found in request.")
                except Exception as e:
                    print("Error processing request (2):", e)
                    raise e
                print("Sending page.")
                conn.sendall(headers + pageHTML)
                conn.close()
                print("Sent page.")
            except Exception as e2:
                print("Connection failed? Sleeping for 5 seconds.", e2)
                conn.close()
                time.sleep(5)
                break

try:
    while True: #Reconnect loop
        print("Starting websocket.")
        jsonParseErrorCount = 0
        try:
            w = client.connect(WEBSOCKET_SERVER)
            deviceInfo = {'action': 'init', 'UUID': UUID, 'TOKEN': token, 'LED_COUNT': LED_COUNT}
            w.send(json.dumps(deviceInfo))
            print("Send device info:", deviceInfo)
        except Exception as e:
            print("Could not connect:", e)
            time.sleep(5)
            continue

        while True: #Websocket read loop
            gc.collect()
            try:
                data = w.recv()
                
                try:
                    JSON = json.loads(data)
                except Exception as e:
                    print('Error parsing JSON: "' + str(e) + '" ' + str(data))
                    if jsonParseErrorCount > 3:
                        raise Exception("Too many JSON errors, reconnecting.")
                    jsonParseErrorCount += 1
                    time.sleep(1.25)
                    continue
                    #raise Exception("Error parsing JSON") #
                print("Got JSON:", JSON)
                if JSON['action'] == 'mode':
                    try:
                        tmp = processData(JSON, LED_COUNT)
                        if ('duration' not in JSON) or ('duration' in JSON and int(JSON['duration']) < 0):
                            TIMED_MODES[-1] = [-1, tmp[0],tmp[1],tmp[2]]
                            safeWrite("datafile", data)
                        else:
                            insIndex = (len(TIMED_MODES) - 1) if ('isQued' in JSON and JSON['isQued'] and str(JSON['isQued']).lower() != "false") else 0
                            TIMED_MODES.insert(insIndex, [int(JSON['duration']) * 100 + time.time_ns() // 1_000_000, tmp[0],tmp[1],tmp[2]])
                        print("Modes:", TIMED_MODES) #Print compiled mode
                    except Exception as e:
                        print("Error parsing mode:", e)
                elif JSON['action'] == 'RGB_ORDER':
                    safeWrite("RGB_ORDER", JSON['RGB_ORDER'])
                    OFFSET_R, OFFSET_G, OFFSET_B = getRGBMode(JSON['RGB_ORDER'])
                    print("RGB offsets ->", OFFSET_R, OFFSET_G, OFFSET_B)
                elif JSON['action'] == 'REVERSE':
                    safeWrite("REVERSE", JSON['REVERSE'])
                    REVERSE = boolStr(JSON['REVERSE']) 
                    print("Reverse ->", REVERSE)
                elif JSON['action'] == 'getTime':
                    RECTIME = time.time_ns() // 1_000_000
                    w.send(json.dumps({'action': 'getTime'}))
                elif JSON['action'] == 'timeDelta':
                    TIMEDELTA = JSON['time'] - RECTIME
                elif JSON['action'] == 'reset':
                    print("Resetting, modes are:", TIMED_MODES)
                    machine.reset()
                    LOOP = False
                del JSON
                del data
            except Exception as e:
                print("Websocket error:", e)
                try:
                    del w
                    del data
                except Exception:
                    pass
                gc.collect()
                time.sleep(5)
                break
            time.sleep(0.2)      
except:
    LOOP = False