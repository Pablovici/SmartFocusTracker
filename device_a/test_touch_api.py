import time
from m5stack import lcd
from machine import I2C, Pin

lcd.clear(0x000000)
lcd.font(lcd.FONT_Default)
lcd.print("Touch I2C test", 90, 5, 0xFFFFFF)
lcd.print("Pose le doigt sur l ecran", 38, 22, 0xAAAAAA)
lcd.line(0, 38, 320, 38, 0x444444)

# FT6336U est sur I2C interne Core2 : SDA=21 SCL=22 addr=0x38
# On teste les deux bus possibles
i2c_list = []
try:
    i2c_list.append(("I2C(0,21,22)", I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)))
except Exception as e:
    lcd.print("bus0 ERR:" + str(e)[:28], 5, 44, 0xFF0000)

try:
    i2c_list.append(("I2C(1,33,32)", I2C(1, scl=Pin(33), sda=Pin(32), freq=400000)))
except Exception as e:
    lcd.print("bus1 ERR:" + str(e)[:28], 5, 62, 0xFF0000)

y = 44
for name, bus in i2c_list:
    try:
        devs = bus.scan()
        has38 = 0x38 in devs
        lcd.print("{} devs={} 0x38={}".format(name, devs, has38), 5, y, 0x00FF00 if has38 else 0xAAAAAA)
    except Exception as e:
        lcd.print("{} ERR:{}".format(name, str(e)[:20]), 5, y, 0xFF0000)
    y += 18

lcd.print("---lecture continue---", 60, y + 4, 0x444444)
y_read = y + 22

# Lecture continue sur le bus qui a 0x38
read_bus = None
for name, bus in i2c_list:
    try:
        if 0x38 in bus.scan():
            read_bus = bus
            break
    except:
        pass

while True:
    if read_bus is None:
        lcd.fillRect(0, y_read, 320, 18, 0x000000)
        lcd.print("FT6336U introuvable sur I2C", 20, y_read, 0xFF0000)
    else:
        try:
            # reg 0x02 = nb points, 0x03-0x06 = x/y premier point
            data = read_bus.readfrom_mem(0x38, 0x02, 5)
            n = data[0] & 0x0F
            if n > 0:
                x = ((data[1] & 0x0F) << 8) | data[2]
                yy = ((data[3] & 0x0F) << 8) | data[4]
                s = "TOUCH n={} x={} y={}".format(n, x, yy)
                col = 0x00FF00
            else:
                s = "no touch (n=0)"
                col = 0xAAAAAA
        except Exception as e:
            s = "read ERR:" + str(e)[:24]
            col = 0xFF0000
        lcd.fillRect(0, y_read, 320, 18, 0x000000)
        lcd.print(s, 5, y_read, col)

    time.sleep_ms(100)
