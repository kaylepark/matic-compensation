"""Peer companies and their public ATS endpoints for live job-posting pulls.

Slugs are best guesses for each company's Greenhouse / Lever board. Some will
be wrong or the company may use a different ATS -- the market fetcher skips any
that 404, so correcting a slug here is the only maintenance needed.

To find a slug:
  - Greenhouse board URL looks like  boards.greenhouse.io/<slug>
  - Lever board URL looks like       jobs.lever.co/<slug>
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Peer:
    name: str
    ats: str  # "greenhouse" | "lever"
    slug: str


PEERS = [
    Peer("Tesla", "greenhouse", "tesla"),
    Peer("Rivian", "greenhouse", "rivian"),
    Peer("Mill", "greenhouse", "mill"),
    Peer("Anduril", "lever", "anduril"),
    Peer("Amazon Lab126", "greenhouse", "lab126"),
    Peer("Sunday Robotics", "greenhouse", "sundayrobotics"),
    Peer("iRobot", "greenhouse", "irobot"),
    Peer("Lucid Motors", "greenhouse", "lucidmotors"),
    Peer("Figure AI", "greenhouse", "figureai"),
    Peer("Cobalt Robotics", "lever", "cobaltrobotics"),
    # Added by Claude -- same robotics / ML / consumer-hardware talent pool:
    Peer("Zipline", "lever", "zipline"),
    Peer("Skydio", "greenhouse", "skydio"),
    Peer("Nuro", "greenhouse", "nuro"),
    Peer("Waymo", "greenhouse", "waymo"),
    Peer("Physical Intelligence", "greenhouse", "physicalintelligence"),
    Peer("Bear Robotics", "lever", "bearrobotics"),
    Peer("Boston Dynamics", "greenhouse", "bostondynamics"),
]
