"""FastPilot code runner: a small FastAPI app on a Unix socket that runs visitor code in slots.

Each slot has its own uid. After every run, every process left behind by that uid is killed, so one
visitor's escaped process cannot watch the next visitor's code.
"""
