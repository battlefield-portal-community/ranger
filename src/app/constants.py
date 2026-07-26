"""Static game reference data shared across cogs.

Values here are curated by hand rather than fetched, so they live outside any
one cog and are imported by whichever features need them.
"""

from __future__ import annotations

# Level id -> display name. Used as a fallback when the gametools API returns
# the raw level id (e.g. "MP_Aftermath_Portal") instead of a friendly map name.
LEVEL_NAMES = {
    "MP_Abbasid": "Siege of Cairo",
    "MP_Aftermath": "Empire State",
    "MP_Aftermath_Portal": "Bellum1988's Operation Metro",
    "MP_Badlands": "Blackwell Fields",
    "MP_Battery": "Iberian Offensive",
    "MP_Capstone": "Liberation Peak",
    "MP_Contaminated": "Contaminated",
    "MP_Dumbo": "Manhattan Bridge",
    "MP_Eastwood": "Eastwood",
    "MP_FireStorm": "Operation Firestorm",
    "MP_GolmudRailway": "Railway to Golmud",
    "MP_Granite_ClubHouse_Portal": "Golf Course",
    "MP_Granite_MainStreet_Portal": "Downtown",
    "MP_Granite_Marina_Portal": "Marina",
    "MP_Granite_MilitaryRnD_Portal": "Area 22B",
    "MP_Granite_MilitaryStorage_Portal": "Redline Storage",
    "MP_Granite_TechCampus_Portal": "Defense Nexus",
    "MP_Granite_Underground_Portal": "Complex 3",
    "MP_Limestone": "Saints Quarter",
    "MP_Outskirts": "New Sobek City",
    "MP_Plaza": "Cairo Bazaar",
    "MP_Portal_Sand": "Portal Sandbox",
    "MP_Subsurface": "Hagental Base",
    "MP_Tungsten": "Mirak Valley",
}

# Level ids the Portal SDK spells differently from the gametools API, as
# SDK id -> the API id keying LEVEL_NAMES. Both name the same map. The SDK
# drops the "_Portal" suffix the API carries on the Granite maps.
#
# Deliberately not derived by stripping "_Portal": MP_Aftermath_Portal would
# alias to MP_Aftermath, which is a different map (Empire State) that the API
# already reports under that exact id.
SDK_LEVEL_ID_ALIASES = {
    "MP_Granite_ClubHouse": "MP_Granite_ClubHouse_Portal",
    "MP_Granite_MainStreet": "MP_Granite_MainStreet_Portal",
    "MP_Granite_Marina": "MP_Granite_Marina_Portal",
    "MP_Granite_MilitaryRnD": "MP_Granite_MilitaryRnD_Portal",
    "MP_Granite_MilitaryStorage": "MP_Granite_MilitaryStorage_Portal",
    "MP_Granite_TechCampus": "MP_Granite_TechCampus_Portal",
    "MP_Granite_Underground": "MP_Granite_Underground_Portal",
}
