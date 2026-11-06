"""Build an SDIF .cl2 entry file with the independent `sdif` library (tdsmith/sdif) to test our reader."""
import sys
from datetime import date
from decimal import Decimal
import sdif.models as m
from sdif.records import encode_record
from sdif.time import Time

import dataclasses, inspect
def mk(cls, **kw):
    sig = inspect.signature(cls)
    for n in sig.parameters:
        kw.setdefault(n, None)
    return cls(**kw)

def T(s):
    return Time.from_str(s)

recs = [
    mk(m.TeamId, organization=m.OrganizationCode.uss, team_code="UTGRAN", name="Grantsville High School",
             abbreviation="Grantsville", city="Grantsville", state="UT", postal_code="84029", region="1"),
]
swimmers = [("Cowboy, Casey", m.SexCode.male, "100 A 1:01.50", "50 A 25.10"),
            ("Rider, Rhonda", m.SexCode.female, "500 A 6:10.22", "100 C 1:15.80"),
            ("Mustang, Mia", m.SexCode.female, "200 E 2:30.00", None)]
STROKE = {"A": m.StrokeCode.freestyle, "C": m.StrokeCode.breaststroke, "E": m.StrokeCode.im}
num = {("M", 100, "A"): "12", ("M", 50, "A"): "8", ("F", 500, "A"): "13", ("F", 100, "C"): "19", ("F", 200, "E"): "5"}
for name, sex, *evs in swimmers:
    for ev in evs:
        if not ev:
            continue
        dist, st, tm = ev.split()
        g = "M" if sex == m.SexCode.male else "F"
        recs.append(mk(m.IndividualEvent, organization=m.OrganizationCode.uss, name=name, ussn=None,
                    birthdate=date(2009, 3, 4), age_or_class="11", sex=sex,
                    event_sex=m.EventSexCode.male if g == "M" else m.EventSexCode.female,
                    event_distance=int(dist), stroke=STROKE[st], event_number=num[(g, int(dist), st)], event_age="UNOV",
                    date_of_swim=date(2026, 11, 5), seed_time=T(tm), seed_time_course=m.CourseStatusCode.short_yards))
recs.append(mk(m.RelayEvent, organization=m.OrganizationCode.uss, relay_team_name="A", team_code="UTGRAN", n_f0_records=2,
            event_sex=m.EventSexCode.female, relay_distance=200, stroke=m.StrokeCode.free_relay, event_number="15",
            event_age="UNOV", swim_date=date(2026, 11, 5), seed_time=T("1:58.40"), seed_course=m.CourseStatusCode.short_yards))
for i, nm in enumerate(["Rider, Rhonda", "Mustang, Mia"], 1):
    recs.append(mk(m.RelayName, organization=m.OrganizationCode.uss, team_code="UTGRAN", relay_team_name="A", swimmer_name=nm,
                birthdate=date(2009, 3, 4), age_or_class="11", sex=m.SexCode.female, finals_order=m.OrderCode(str(i))))
open(sys.argv[1], "w").write("".join(encode_record(r, False).rstrip("\r\n") + "\r\n" for r in recs))
print(open(sys.argv[1]).read()[:2000])
