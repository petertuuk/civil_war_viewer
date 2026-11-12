"""Theater of an order-of-battle placement: 'E' (Virginia, the Carolinas, the Atlantic coast), 'W' (west of the
Appalachians and beyond), or None. From the battle article title, army, corps or the OR table heading."""
import re

EAST = re.compile(r"northern virginia|potomac|valley district|shenandoah|richmond|petersburg|james|peninsula|manassas|"
                  r"bull run|maryland|antietam|fredericksburg|chancellorsville|gettysburg|wilderness|spotsylvania|"
                  r"cold harbor|seven days|seven pines|williamsburg|cedar mountain|cedar creek|chantilly|kernstown|"
                  r"winchester|port republic|cross keys|mcdowell|monocacy|fort stevens|lynchburg|piedmont|new market|"
                  r"cloyd|bristoe|mine run|trevilian|deep bottom|crater|globe tavern|ream|peebles|boydton|hatcher|"
                  r"darbytown|chaffin|drewry|bermuda|wilmington|fort fisher|bentonville|wyse|averasboro|olustee|"
                  r"honey hill|carolinas campaign|charleston|appomattox|five forks|fort stedman|ball's bluff|"
                  r"brandy station|suffolk|new bern|first corps|second corps|third army corps|second army corps|"
                  r"light division|jackson's", re.I)
WEST = re.compile(r"army of tennessee|army of mississippi|army of the west|kentucky|atlanta|chickamauga|chattanooga|"
                  r"missionary|stones river|murfreesboro|perryville|shiloh|corinth|vicksburg|port hudson|franklin|"
                  r"nashville|knoxville|meridian|mobile|arkansas|missouri|trans-mississippi|louisiana|texas|red river|"
                  r"pea ridge|prairie grove|wilson's creek|fort donelson|fort henry|belmont|mill springs|island number|"
                  r"iuka|chickasaw|champion hill|port gibson|raymond|big black|tupelo|brice|peachtree|jonesbor|"
                  r"new hope|kennesaw|resaca|polk's|hardee's|cheatham's|breckinridge's|withers'|forrest", re.I)


def classify(*texts):
    t = " ".join(x for x in texts if x)
    e, w = bool(EAST.search(t)), bool(WEST.search(t))
    if e and not w:
        return "E"
    if w and not e:
        return "W"
    if re.search(r"northern virginia|potomac", t, re.I):
        return "E"
    if re.search(r"army of tennessee|army of mississippi|army of the cumberland|army of the ohio|trans-mississippi", t, re.I):
        return "W"
    return None
