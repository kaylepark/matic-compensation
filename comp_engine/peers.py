"""Peer companies and their public ATS endpoints for live job-posting pulls.

Supported ATS platforms:
  - Greenhouse: boards-api.greenhouse.io/v1/boards/<slug>/jobs
  - Lever:      api.lever.co/v0/postings/<slug>
  - Ashby:      api.ashbyhq.com/posting-api/job-board/<slug>

Companies on Workday, iCIMS, or custom ATS (Tesla, Rivian, iRobot,
Amazon Lab126, Boston Dynamics, Bear Robotics) don't have a clean public
JSON API we can hit, so they're excluded for now. The market fetcher
skips any peer that 404s, so adding a wrong slug is harmless.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Peer:
    name: str
    ats: str  # "greenhouse" | "lever" | "ashby"
    slug: str


PEERS = [
    # --- User's primary peer list ---
    Peer("Mill", "greenhouse", "mill"),
    Peer("Anduril", "greenhouse", "andurilindustries"),
    Peer("Lucid Motors", "greenhouse", "lucidmotors"),
    Peer("Figure AI", "greenhouse", "figureai"),
    Peer("Cobalt Robotics", "lever", "cobaltrobotics"),
    Peer("Sunday Robotics", "ashby", "sunday"),
    # --- Extended talent-pool peers ---
    Peer("Zipline", "greenhouse", "flyzipline"),
    Peer("Skydio", "ashby", "skydio"),
    Peer("Nuro", "greenhouse", "nuro"),
    Peer("Waymo", "greenhouse", "waymo"),
    Peer("Physical Intelligence", "ashby", "physicalintelligence"),
    # --- Not auto-pullable (Workday / iCIMS / custom ATS) ---
    # Tesla          — custom ATS (tesla.com/careers)
    # Rivian         — iCIMS (us-careers-rivian.icims.com)
    # iRobot         — Workday (irobot.wd5.myworkdayjobs.com/iRobot)
    # Amazon Lab126  — Amazon internal (amazon.jobs/en/teams/lab126)
    # Boston Dynamics — Workday (bostondynamics.wd1.myworkdayjobs.com)
    # Bear Robotics  — Breezy HR (bear-robotics.breezy.hr)
]
