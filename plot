import re
import matplotlib.pyplot as plt
from datetime import datetime

filename = "/home/greatestgroup13/gas_readings.txt"

times = []
oxidising = []
reducing = []
nh3 = []

current_time = None
current_oxidising = None
current_reducing = None
current_nh3 = None

with open(filename, "r") as file:

    for line in file:

        # Get timestamp and oxidising reading
        match = re.search(
            r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+).*?"
            r"Oxidising:\s*([\d.]+)",
            line
        )

        if match:
            current_time = match.group(1)
            current_oxidising = float(match.group(2))
            continue

        # Get reducing reading
        match = re.search(
            r"Reducing:\s*([\d.]+)",
            line
        )

        if match:
            current_reducing = float(match.group(1))
            continue

        # Get NH3 reading
        match = re.search(
            r"NH3:\s*([\d.]+)",
            line
        )

        if match:
            current_nh3 = float(match.group(1))

            # We now have one complete measurement
            if (
                current_time is not None
                and current_oxidising is not None
                and current_reducing is not None
            ):
                times.append(current_time)
                oxidising.append(current_oxidising)
                reducing.append(current_reducing)
                nh3.append(current_nh3)

            # Reset
            current_time = None
            current_oxidising = None
            current_reducing = None
            current_nh3 = None


# Make sure data was actually found
if len(times) == 0:
    print("No gas readings were found.")
    print("Check that the filename and log format are correct.")
    exit()

print(f"Found {len(times)} measurements.")

# Convert timestamps into actual elapsed time
datetime_values = [
    datetime.strptime(t, "%Y-%m-%d %H:%M:%S.%f")
    for t in times
]

start_time = datetime_values[0]

time_seconds = [
    (t - start_time).total_seconds()
    for t in datetime_values
]

print(f"Start time: {times[0]}")
print(f"End time:   {times[-1]}")
print(f"Duration:   {time_seconds[-1]:.1f} seconds")
print(f"Duration:   {time_seconds[-1] / 60:.2f} minutes")

time_minutes = [t / 60 for t in time_seconds]


#PLOT CHECK
print("\n--- DATA RANGES ---")

print(f"Oxidising: {min(oxidising):.2f} to {max(oxidising):.2f} Ohms")
print(f"Reducing:  {min(reducing):.2f} to {max(reducing):.2f} Ohms")
print(f"NH3:       {min(nh3):.2f} to {max(nh3):.2f} Ohms")

print("\n--- TIME ---")
print(f"Start: {times[0]}")
print(f"End:   {times[-1]}")
print(f"Duration: {time_seconds[-1]:.2f} seconds")
print(f"Duration: {time_seconds[-1]/60:.2f} minutes")

# -------------------------
# Oxidising
# -------------------------

plt.figure()
plt.plot(time_minutes, oxidising, marker="o")
plt.xlabel("Time (minutes)")
plt.ylabel("Resistance (Ohms)")
plt.title("MiCS-6814 Oxidising Sensor")
plt.grid(True)
plt.xlim(0, time_minutes[-1])
plt.tight_layout()
plt.savefig("gas_plots/oxidising.png")
plt.show()


# -------------------------
# Reducing
# -------------------------

plt.figure()
plt.plot(time_minutes, reducing, marker="o")
plt.xlabel("Time (minutes)")
plt.ylabel("Resistance (Ohms)")
plt.title("MiCS-6814 Reducing Sensor")
plt.grid(True)
plt.xlim(0, time_minutes[-1])
plt.tight_layout()
plt.savefig("gas_plots/reducing.png")
plt.show()


# -------------------------
# NH3
# -------------------------

plt.figure()
plt.plot(time_minutes, nh3, marker="o")
plt.xlabel("Time (minutes)")
plt.ylabel("Resistance (Ohms)")
plt.title("MiCS-6814 NH3 Sensor")
plt.grid(True)
plt.xlim(0, time_minutes[-1])
plt.tight_layout()
plt.savefig("gas_plots/nh3.png")
plt.show()

plt.savefig("gas_plots/oxidising.png")
plt.savefig("gas_plots/reducing.png")
plt.savefig("gas_plots/nh3.png")
plt.show()