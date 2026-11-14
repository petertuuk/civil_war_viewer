# Civil War, Day by Day

A map with a timeline showing where every regiment, battery and company of the American Civil War was, day by day,
from 1861 to 1865, with the source for every position.

**See the map:** https://petertuuk.github.io/civil_war_viewer/ · [About, sources and limits](viewer/site/about.html)

Positions come from Frederick Dyer's *Compendium of the War of the Rebellion* (1908), the *Official Records* (1880–1901),
National Park Service unit lists and histories, Wikipedia orders of battle, state unit histories and battlefield
monuments. A Python pipeline turns each source into dated claims ("this unit was at this place on this day, per this
source"), locates the places, links units across sources, and checks every placement against the unit's own route.
The claims go into a SQLite database, and the map is a static page that reads JSON exported from it.

Found a mistake? [Open an issue](https://github.com/petertuuk/civil_war_viewer/issues/new) with the unit, the date
and your source.

## Layout

- `pipeline/`: the extraction and checking pipeline; `pipeline/README.md` indexes the scripts and
  `pipeline/rebuild.sh` runs the stages in order
- `data/`: hand-made inputs only (overrides, decisions, answer keys, the timeline's events); downloaded sources and
  everything the pipeline builds are left out of git (see `.gitignore`)
- `viewer/war/index.html`: the map; `viewer/site/`: the About page, icon, fonts and MapLibre for the website
- `pipeline/build_site.py`, `pipeline/deploy_site.sh`: build the website and publish it to the `gh-pages` branch

## Licenses and credits

The code is under the [MIT License](LICENSE). The historical records are in the public domain. Material derived from
Wikipedia is CC BY-SA 4.0, OpenStreetMap data is © OpenStreetMap contributors (ODbL), and the CWSAC battle data comes
through Jeffrey B. Arnold's [acw_battle_data](https://github.com/jrnold/acw_battle_data) (BSD 3-Clause).

Battlefield positions: Antietam regiment positions from Brian Downey's [Antietam on the Web](https://antietam.aotw.org/)
battle maps (CC BY-NC-SA 4.0, so data derived from them is non-commercial and share-alike), georeferenced against the
Antietam Battlefield Board's Carman–Cope map on [Map Warper](https://mapwarper.net/); monument and tablet locations from
the National Park Service's [NPGallery](https://npgallery.nps.gov/) and the ShilohWeb map of the Shiloh tablets; and
the [Georgia Historical Society](https://www.georgiahistory.com/)'s historical markers for the Atlanta campaign. The map uses
[MapLibre GL JS](https://maplibre.org/) (BSD 3-Clause) and IBM Plex fonts (SIL Open Font License 1.1).
