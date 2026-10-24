import logging
import time

from enviroplus import gas

logging.basicConfig(
    filename="/home/greatestgroup13/gas_readings.txt",
    format="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S"
)

logging.info("""gas.py - Print readings from the MICS6814 Gas sensor.

Starting gas sensor logging...
""")

try:
    while True:
        readings = gas.read_all()
        logging.info(readings)
        time.sleep(1.0)

except KeyboardInterrupt:
    logging.info("Gas sensor logging stopped.")
