import com.healthmarketscience.jackcess.*;
import org.json.*;

import java.io.File;
import java.nio.file.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;

/**
 * Builds a Hy-Tek Meet Manager database from a template MDB plus a JSON spec.
 *
 *   java Builder template.mdb spec.json out.mdb
 *
 * The template keeps its events, sessions, scoring, records, officials and
 * preferences. Teams, athletes, entries, relays and dual-meet pairings are
 * replaced. Every row is written with the same padding/defaults Meet Manager
 * uses in the template, so MM sees it as one of its own.
 * Prints a JSON report on stdout.
 */
public class Builder {
    static final String[] PROFILED = {"RelayNames", "Relay", "Entry", "Split", "Athlete", "TeamCoaches", "Team", "Dualteams", "Records", "RecordTags"};
    static final String[] CLEAR = {"RelayNames", "Relay", "Entry", "Split", "Athlete", "TeamCoaches", "Team", "Dualteams"};

    // per-table column info learned from the template before it is cleared
    static Map<String, Map<String, Object>> defaults = new HashMap<>();
    static Map<String, Set<String>> padded = new HashMap<>();
    static JSONArray warnings = new JSONArray();

    static JSONObject profile = new JSONObject();

    public static void main(String[] a) throws Exception {
        if (a[0].equals("--profile")) { writeProfile(a[1], a[2]); return; }
        Path prof = Paths.get(System.getProperty("mm.profile", "/opt/mmdb/profile.json"));
        if (Files.exists(prof)) profile = new JSONObject(Files.readString(prof));
        if (a[0].equals("--read-master")) { readMaster(a[1]); return; }
        if (a[0].equals("--write-master")) { writeMaster(a[1], a[2]); return; }
        Path tpl = Paths.get(a[0]), out = Paths.get(a[2]);
        JSONObject spec = new JSONObject(Files.readString(Paths.get(a[1])));
        Files.copy(tpl, out, StandardCopyOption.REPLACE_EXISTING);

        try (Database db = new DatabaseBuilder(out.toFile()).setAutoSync(false).open()) {
            for (String t : CLEAR) learn(db.getTable(t));
            for (String t : CLEAR) {
                Table tb = db.getTable(t);
                Cursor c = CursorBuilder.createCursor(tb);
                while (c.moveToNextRow()) c.deleteCurrentRow();
            }
            for (String t : new String[]{"Team", "Athlete", "Relay", "TeamCoaches"})
                db.getTable(t).setAllowAutoNumberInsert(true);

            // ---- events ----
            Map<String, Integer> events = new HashMap<>();
            Table ev = db.getTable("Event");
            Cursor ec = CursorBuilder.createCursor(ev);
            while (ec.moveToNextRow()) {
                Row r = ec.getCurrentRow();
                String key = evKey(((Number) r.get("Event_no")).intValue(), str(r.get("Event_gender")),
                        ((Number) r.get("Event_dist")).intValue(), str(r.get("Event_stroke")), str(r.get("Ind_rel")));
                events.put(key, (Integer) r.get("Event_ptr"));
                // reset per-meet run state left over from the template meet
                Map<String, Object> upd = new HashMap<>();
                JSONObject notes = spec.optJSONObject("event_notes");
                String evNo = String.valueOf(((Number) r.get("Event_no")).intValue());
                if (notes != null && notes.has(evNo) && ev.getColumn("Comm_1") != null)
                    putRaw(upd, ev, "Comm_1", notes.getString(evNo));
                for (String col : new String[]{"Fin_AwardsPrinted", "Pre_AwardsPrinted", "Sem_AwardsPrinted", "Is_locked"})
                    if (ev.getColumn(col) != null) upd.put(col, false);
                for (String col : new String[]{"fin_actualstarttime", "sem_actualstarttime", "pre_actualstarttime"})
                    if (ev.getColumn(col) != null) upd.put(col, 0);
                ec.updateCurrentRowFromMap(upd);
            }

            // ---- teams ----
            Table team = db.getTable("Team");
            Map<String, Integer> teamNo = new HashMap<>();
            JSONArray teams = spec.getJSONArray("teams");
            for (int i = 0; i < teams.length(); i++) {
                JSONObject t = teams.getJSONObject(i);
                int no = i + 1;
                Map<String, Object> r = base("Team", team);
                r.put("Team_no", no);
                put(r, team, "Team_name", t.optString("name"));
                put(r, team, "Team_short", t.optString("short"));
                put(r, team, "Team_abbr", t.optString("abbr"));
                put(r, team, "Team_lsc", t.optString("lsc"));
                put(r, team, "Team_addr1", t.optString("addr1"));
                put(r, team, "Team_addr2", t.optString("addr2"));
                put(r, team, "Team_city", t.optString("city"));
                put(r, team, "Team_statenew", t.optString("state"));
                put(r, team, "Team_zip", t.optString("zip"));
                put(r, team, "Team_cntry", t.optString("country", "USA"));
                put(r, team, "Team_daytele", t.optString("phone"));
                put(r, team, "Team_email", t.optString("email"));
                team.addRowFromMap(r);
                teamNo.put(t.getString("key"), no);
            }

            // ---- athletes ----
            Table ath = db.getTable("Athlete");
            Map<String, Integer> athNo = new HashMap<>();
            Map<String, Integer> athAge = new HashMap<>();
            Map<String, Integer> athTeam = new HashMap<>();
            JSONArray aths = spec.getJSONArray("athletes");
            for (int i = 0; i < aths.length(); i++) {
                JSONObject s = aths.getJSONObject(i);
                Integer tn = teamNo.get(s.getString("team"));
                if (tn == null) { warn("Athlete " + s.optString("last") + " has unknown team " + s.getString("team")); continue; }
                int no = i + 1;
                Map<String, Object> r = base("Athlete", ath);
                r.put("Ath_no", no);
                r.put("Comp_no", no);
                put(r, ath, "Last_name", s.optString("last"));
                put(r, ath, "First_name", s.optString("first"));
                put(r, ath, "Initial", s.optString("initial"));
                put(r, ath, "Pref_name", s.optString("pref"));
                put(r, ath, "Ath_Sex", s.optString("sex"));
                put(r, ath, "Schl_yr", s.optString("class"));
                r.put("Team_no", tn);
                if (s.optInt("age", 0) > 0) r.put("Ath_age", s.getInt("age"));
                if (!s.optString("dob").isEmpty())
                    r.put("Birth_date", LocalDate.parse(s.getString("dob")).atStartOfDay());
                ath.addRowFromMap(r);
                athNo.put(s.getString("key"), no);
                athAge.put(s.getString("key"), s.optInt("age", 0));
                athTeam.put(s.getString("key"), tn);
            }

            // ---- individual entries ----
            Table ent = db.getTable("Entry");
            JSONArray ents = spec.getJSONArray("entries");
            int nEnt = 0, nSeeded = 0;
            for (int i = 0; i < ents.length(); i++) {
                JSONObject e = ents.getJSONObject(i);
                Integer ptr = events.get(evKey(e.getInt("event_no"), e.getString("gender"), e.getInt("distance"), e.getString("stroke"), "I"));
                Integer an = athNo.get(e.getString("athlete"));
                if (ptr == null) { warn("No matching event in the template for #" + e.getInt("event_no") + " " + e.optString("label") + " (" + e.optString("who") + ") - entry skipped"); continue; }
                if (an == null) { warn("Entry for unknown athlete " + e.getString("athlete")); continue; }
                Map<String, Object> r = base("Entry", ent);
                r.put("Event_ptr", ptr);
                r.put("Ath_no", an);
                seed(r, ent, e);
                if (athAge.getOrDefault(e.getString("athlete"), 0) > 0 && ent.getColumn("event_age") != null)
                    r.put("event_age", athAge.get(e.getString("athlete")));
                if (e.optBoolean("exh")) put(r, ent, "Fin_exh", "X");
                if (e.has("lane")) { r.put("Fin_heat", (short) e.getInt("heat")); r.put("Fin_lane", (short) e.getInt("lane")); nSeeded++; }
                ent.addRowFromMap(r);
                nEnt++;
            }

            // ---- relays ----
            Table rel = db.getTable("Relay");
            Table rn = db.getTable("RelayNames");
            JSONArray rels = spec.getJSONArray("relays");
            int nRel = 0, relNo = 0;
            boolean crossTeam = false;
            for (int i = 0; i < rels.length(); i++) {
                JSONObject e = rels.getJSONObject(i);
                Integer ptr = events.get(evKey(e.getInt("event_no"), e.getString("gender"), e.getInt("distance"), e.getString("stroke"), "R"));
                Integer tn = teamNo.get(e.getString("team"));
                if (ptr == null) { warn("No matching relay event in the template for #" + e.getInt("event_no") + " " + e.optString("label") + " - relay skipped"); continue; }
                if (tn == null) { warn("Relay for unknown team " + e.getString("team")); continue; }
                relNo++;
                String ltr = e.optString("letter", "A");
                Map<String, Object> r = base("Relay", rel);
                r.put("Relay_no", relNo);
                r.put("Event_ptr", ptr);
                r.put("Team_no", tn);
                put(r, rel, "Team_ltr", ltr);
                put(r, rel, "Rel_sex", e.getString("gender").equals("W") ? "F" : e.getString("gender"));
                if (e.has("lane")) { r.put("Fin_heat", (short) e.getInt("heat")); r.put("Fin_lane", (short) e.getInt("lane")); nSeeded++; }
                seed(r, rel, e);
                rel.addRowFromMap(r);
                nRel++;
                JSONObject legs = e.optJSONObject("legs");
                if (legs != null)
                    for (String leg : legs.keySet()) {
                        Integer an = athNo.get(legs.getString(leg));
                        if (an == null) { warn("Relay leg athlete not found: " + legs.getString(leg)); continue; }
                        if (!tn.equals(athTeam.get(legs.getString(leg)))) crossTeam = true;
                        Map<String, Object> n = base("RelayNames", rn);
                        n.put("Event_ptr", ptr);
                        n.put("Team_no", tn);
                        put(n, rn, "Team_ltr", ltr);
                        n.put("Ath_no", an);
                        n.put("Pos_no", Integer.parseInt(leg));
                        put(n, rn, "Event_round", "F");
                        n.put("Relay_no", relNo);
                        rn.addRowFromMap(n);
                    }
            }

            // ---- dual meet pairings: every team vs every other, girls and boys ----
            Table dual = db.getTable("Dualteams");
            List<Integer> scoring = new ArrayList<>();
            for (Object k : spec.getJSONArray("scoring_teams")) if (teamNo.containsKey((String) k)) scoring.add(teamNo.get((String) k));
            if (scoring.size() >= 2)
                for (String g : new String[]{"F", "M"})
                    for (int x = 0; x < scoring.size(); x++)
                        for (int y = x + 1; y < scoring.size(); y++) {
                            Map<String, Object> r = base("Dualteams", dual);
                            r.put("team_gender", g);
                            r.put("ateam_no", scoring.get(x));
                            r.put("bteam_no", scoring.get(y));
                            dual.addRowFromMap(r);
                        }

            // ---- team-record tags (e.g. "Varsity Rec") belong to the home team of THIS meet ----
            Table tags = db.getTable("RecordTags");
            Set<Integer> teamTags = new HashSet<>();
            for (Object k : spec.optJSONArray("team_tags") == null ? new JSONArray() : spec.getJSONArray("team_tags")) teamTags.add(((Number) k).intValue());
            String recTeam = spec.optString("record_team", "");
            Integer recTeamNo = teamNo.getOrDefault(recTeam, 0);
            Cursor tc = CursorBuilder.createCursor(tags);
            while (tc.moveToNextRow()) {
                Row r = tc.getCurrentRow();
                int ptr = (Integer) r.get("tag_ptr");
                Object cur = r.get("team_no");
                boolean isTeamTag = teamTags.contains(ptr) || (spec.optJSONArray("team_tags") == null && cur != null && ((Number) cur).intValue() > 0);
                if (isTeamTag) tc.updateCurrentRowFromMap(new HashMap<>(Map.of("team_no", recTeamNo)));
                else if (cur != null && ((Number) cur).intValue() > 0) tc.updateCurrentRowFromMap(new HashMap<>(Map.of("team_no", 0)));  // stale team from template
            }

            // ---- meet record ----
            Table meet = db.getTable("Meet");
            Cursor mc = CursorBuilder.createCursor(meet);
            mc.moveToNextRow();
            JSONObject m = spec.getJSONObject("meet");
            Map<String, Object> mu = new HashMap<>();
            putRaw(mu, meet, "Meet_name1", m.getString("name"));
            if (!m.optString("date").isEmpty()) {
                LocalDateTime d = LocalDate.parse(m.getString("date")).atStartOfDay();
                mu.put("Meet_start", d);
                mu.put("Meet_end", d);
            }
            if (!m.optString("location").isEmpty()) putRaw(mu, meet, "Meet_location", m.getString("location"));
            JSONObject lanes = spec.getJSONObject("lanes");
            mu.put("meet_numlanes", lanes.getInt("count"));
            mu.put("meet_meetstyle", scoring.size() >= 3 ? 3 : (scoring.size() == 2 ? 2 : 1));
            for (int i = 1; i <= 12; i++) if (meet.getColumn("dualteam_lane" + i) != null) mu.put("dualteam_lane" + i, 0);
            JSONArray plan = lanes.getJSONArray("plan");
            for (int i = 0; i < plan.length(); i++) {
                JSONObject l = plan.getJSONObject(i);
                Integer tn = teamNo.get(l.getString("team"));
                int lane = l.getInt("lane");
                int slot = lane == 0 ? 10 : lane;  // MM: the lane-0 team goes in the Lane 10 slot
                if (tn != null && meet.getColumn("dualteam_lane" + slot) != null) mu.put("dualteam_lane" + slot, tn);
            }
            mu.put("dual_evenodd", plan.length() > 0);   // "Use Lane Assignments Above"
            if (crossTeam) mu.put("anyone_onrelay", true);
            putRaw(mu, meet, "Last_updated", LocalDateTime.now().format(DateTimeFormatter.ofPattern("M/d/yyyy h:mm:ss a")));
            mc.updateCurrentRowFromMap(mu);
            resetOnline(db);
            db.flush();

            JSONObject rep = new JSONObject();
            rep.put("teams", teamNo.size()).put("athletes", athNo.size()).put("entries", nEnt).put("relays", nRel)
               .put("meet_style", mu.get("meet_meetstyle")).put("anyone_on_relay", crossTeam).put("preseeded", nSeeded).put("warnings", warnings);
            System.out.println(rep);
        }
    }

    /** A new meet must not inherit the template meet's Meet Mobile / online-entry meet id or upload flags. */
    static void resetOnline(Database db) throws Exception {
        for (String tn : new String[]{"MEETMOBILE2OPTIONS", "OMEOPTIONS"}) {
            if (!db.getTableNames().contains(tn)) continue;
            Table t = db.getTable(tn);
            Cursor c = CursorBuilder.createCursor(t);
            while (c.moveToNextRow()) {
                Map<String, Object> u = new HashMap<>();
                for (Column col : t.getColumns()) {
                    String n = col.getName().toLowerCase();
                    if (n.endsWith("meetid") && col.getType() == DataType.LONG) u.put(col.getName(), 0);
                    if ((n.endsWith("_uploaded") || n.equals("contract_agreed")) && col.getType() == DataType.BOOLEAN) u.put(col.getName(), false);
                }
                if (!u.isEmpty()) c.updateCurrentRowFromMap(u);
            }
        }
    }

    static String evKey(int no, String g, int dist, String stroke, String ir) {
        g = g.equals("W") ? "F" : g;
        return no + "|" + g + "|" + dist + "|" + stroke + "|" + ir;
    }

    static String str(Object o) { return o == null ? "" : o.toString().trim(); }

    static void warn(String s) { warnings.put(s); }

    static final String[] MEET_FIELDS = {"Meet_name1", "Meet_location", "Meet_addr1", "Meet_city", "Meet_state", "Meet_zip"};

    static String t(Object o) { return o == null ? "" : o.toString().trim(); }

    /** Dump the parts of a master DB the web UI edits: meet info, record tags, records, events. */
    static void readMaster(String mdb) throws Exception {
        JSONObject o = new JSONObject();
        try (Database db = new DatabaseBuilder(new File(mdb)).setReadOnly(true).open()) {
            Row m = db.getTable("Meet").iterator().next();
            JSONObject meet = new JSONObject();
            for (String f : MEET_FIELDS) meet.put(f, t(m.get(f)));
            meet.put("Meet_start", t(m.get("Meet_start")));
            o.put("meet", meet);
            JSONArray tags = new JSONArray();
            for (Row r : db.getTable("RecordTags"))
                tags.put(new JSONObject().put("tag_ptr", r.get("tag_ptr")).put("order", r.get("tag_order")).put("name", t(r.get("tag_name")))
                        .put("flag", t(r.get("tag_flag"))).put("team_no", r.get("team_no") == null ? 0 : r.get("team_no")));
            o.put("tags", tags);
            JSONArray recs = new JSONArray();
            for (Row r : db.getTable("Records"))
                recs.put(new JSONObject().put("tag_ptr", r.get("tag_ptr")).put("gender", t(r.get("tag_gender"))).put("indrel", t(r.get("tag_indrel")))
                        .put("dist", r.get("tag_dist")).put("stroke", t(r.get("tag_stroke")))
                        .put("holder", t(r.get("Record_Holder"))).put("team", t(r.get("Record_Holderteam"))).put("relay_names", t(r.get("Relay_Names")))
                        .put("time", r.get("Record_Time") == null ? 0 : ((Number) r.get("Record_Time")).doubleValue())
                        .put("year", r.get("Record_year") == null ? 0 : r.get("Record_year")).put("month", r.get("Record_month") == null ? 0 : r.get("Record_month"))
                        .put("day", r.get("Record_day") == null ? 0 : r.get("Record_day")).put("course", t(r.get("Record_course"))));
            o.put("records", recs);
            JSONArray evs = new JSONArray();
            for (Row r : db.getTable("Event"))
                evs.put(new JSONObject().put("no", r.get("Event_no")).put("gender", t(r.get("Event_gender"))).put("indrel", t(r.get("Ind_rel")))
                        .put("dist", ((Number) r.get("Event_dist")).intValue()).put("stroke", t(r.get("Event_stroke"))));
            o.put("events", evs);
            o.put("counts", new JSONObject().put("teams", db.getTable("Team").getRowCount()).put("athletes", db.getTable("Athlete").getRowCount())
                    .put("entries", db.getTable("Entry").getRowCount()).put("sessions", db.getTable("Session").getRowCount())
                    .put("officials", db.getTable("Officials").getRowCount()));
        }
        System.out.println(o);
    }

    /** Apply UI edits to a master DB in place: {meet:{...}, tags:[...], records:[...] (full replace), clear_people:true}. */
    static void writeMaster(String mdb, String changes) throws Exception {
        JSONObject c = new JSONObject(Files.readString(Paths.get(changes)));
        try (Database db = new DatabaseBuilder(new File(mdb)).setAutoSync(false).open()) {
            if (c.optBoolean("clear_people")) {      // make a clean master out of a real meet backup
                for (String tn : CLEAR) learn(db.getTable(tn));
                for (String tn : CLEAR) { Cursor cu = CursorBuilder.createCursor(db.getTable(tn)); while (cu.moveToNextRow()) cu.deleteCurrentRow(); }
                resetOnline(db);
            }
            if (c.has("meet")) {
                Table mt = db.getTable("Meet");
                Cursor mc = CursorBuilder.createCursor(mt); mc.moveToNextRow();
                Map<String, Object> u = new HashMap<>();
                JSONObject m = c.getJSONObject("meet");
                for (String f : MEET_FIELDS) if (m.has(f) && mt.getColumn(f) != null) {
                    String v = m.getString(f).trim();
                    if (v.isEmpty()) u.put(f, null); else putRaw(u, mt, f, v);
                }
                if (c.optBoolean("clear_people")) {
                    for (int i = 1; i <= 12; i++) if (mt.getColumn("dualteam_lane" + i) != null) u.put("dualteam_lane" + i, 0);
                    u.put("meet_meetstyle", 1);
                    u.put("dual_evenodd", false);
                }
                mc.updateCurrentRowFromMap(u);
            }
            Table tg = db.getTable("RecordTags");
            if (c.has("tags")) {
                learn(tg);
                tg.setAllowAutoNumberInsert(true);
                JSONArray tags = c.getJSONArray("tags");
                Set<Integer> keep = new HashSet<>();
                for (int i = 0; i < tags.length(); i++) keep.add(tags.getJSONObject(i).getInt("tag_ptr"));
                Cursor cu = CursorBuilder.createCursor(tg);
                Set<Integer> have = new HashSet<>();
                while (cu.moveToNextRow()) {
                    int ptr = (Integer) cu.getCurrentRow().get("tag_ptr");
                    if (!keep.contains(ptr)) { cu.deleteCurrentRow(); continue; }
                    have.add(ptr);
                    JSONObject j = find(tags, ptr);
                    Map<String, Object> u = new HashMap<>();
                    put(u, tg, "tag_name", j.getString("name"));
                    put(u, tg, "tag_flag", j.optString("flag", "*").isEmpty() ? "*" : j.optString("flag", "*"));
                    u.put("tag_order", (short) j.optInt("order", 1));
                    u.put("team_no", 0);   // team-record tags are pointed at the home team when a meet is built
                    cu.updateCurrentRowFromMap(u);
                }
                for (int i = 0; i < tags.length(); i++) {
                    JSONObject j = tags.getJSONObject(i);
                    if (have.contains(j.getInt("tag_ptr"))) continue;
                    Map<String, Object> r = base("RecordTags", tg);
                    r.put("tag_ptr", j.getInt("tag_ptr"));
                    put(r, tg, "tag_name", j.getString("name"));
                    put(r, tg, "tag_flag", j.optString("flag", "*").isEmpty() ? "*" : j.optString("flag", "*"));
                    r.put("tag_order", (short) j.optInt("order", i + 1));
                    r.put("team_no", 0);
                    r.put("allow_exh", true);
                    tg.addRowFromMap(r);
                }
            }
            if (c.has("records")) {
                Table rt = db.getTable("Records");
                learn(rt);
                Cursor cu = CursorBuilder.createCursor(rt);
                while (cu.moveToNextRow()) cu.deleteCurrentRow();
                JSONArray recs = c.getJSONArray("records");
                for (int i = 0; i < recs.length(); i++) {
                    JSONObject j = recs.getJSONObject(i);
                    Map<String, Object> r = base("Records", rt);
                    r.put("tag_ptr", j.getInt("tag_ptr"));
                    put(r, rt, "tag_gender", j.getString("gender"));
                    put(r, rt, "tag_indrel", j.getString("indrel"));
                    r.put("tag_dist", j.getInt("dist"));
                    put(r, rt, "tag_stroke", j.getString("stroke"));
                    r.put("low_age", (short) 0);
                    r.put("high_Age", (short) 109);
                    put(r, rt, "Record_Holder", j.optString("holder"));
                    put(r, rt, "Record_Holderteam", j.optString("team"));
                    put(r, rt, "Relay_Names", j.optString("relay_names"));
                    r.put("Record_Time", (float) j.getDouble("time"));
                    put(r, rt, "Record_course", j.optString("course", "Y").isEmpty() ? "Y" : j.optString("course", "Y"));
                    r.put("Record_year", (short) j.optInt("year", 0));
                    r.put("Record_month", (short) j.optInt("month", 0));
                    r.put("Record_day", (short) j.optInt("day", 0));
                    rt.addRowFromMap(r);
                }
            }
            db.flush();
        }
        readMaster(mdb);
    }

    static JSONObject find(JSONArray a, int ptr) {
        for (int i = 0; i < a.length(); i++) if (a.getJSONObject(i).getInt("tag_ptr") == ptr) return a.getJSONObject(i);
        return null;
    }

    /** Save learned defaults/padding of a populated MM database, for templates whose tables are empty. */
    static void writeProfile(String mdb, String out) throws Exception {
        JSONObject o = new JSONObject();
        try (Database db = new DatabaseBuilder(new File(mdb)).setReadOnly(true).open()) {
            for (String t : PROFILED) {
                Table tb = db.getTable(t);
                if (tb.getRowCount() == 0) continue;
                learn(tb);
                JSONObject d = new JSONObject();
                for (Map.Entry<String, Object> e : defaults.get(t).entrySet()) {
                    Object v = e.getValue();
                    d.put(e.getKey(), new JSONArray().put(v.getClass().getSimpleName()).put(v.toString()));
                }
                o.put(t, new JSONObject().put("defaults", d).put("padded", new JSONArray(padded.get(t))));
            }
        }
        Files.writeString(Paths.get(out), o.toString(1));
    }

    static Object typed(String type, String v) {
        switch (type) {
            case "Boolean": return Boolean.parseBoolean(v);
            case "Byte": return Byte.parseByte(v);
            case "Short": return Short.parseShort(v);
            case "Integer": return Integer.parseInt(v);
            case "Float": return Float.parseFloat(v);
            case "Double": return Double.parseDouble(v);
            case "BigDecimal": return new java.math.BigDecimal(v);
            default: return v;
        }
    }

    /** Learn defaults (blank-ish most common value) and padding from template rows. */
    static void learn(Table t) {
        if (t.getRowCount() == 0 && profile.has(t.getName())) {
            JSONObject p = profile.getJSONObject(t.getName());
            Map<String, Object> def = new HashMap<>();
            JSONObject d = p.getJSONObject("defaults");
            for (String k : d.keySet()) if (t.getColumn(k) != null) def.put(k, typed(d.getJSONArray(k).getString(0), d.getJSONArray(k).getString(1)));
            Set<String> pads = new HashSet<>();
            for (Object k : p.getJSONArray("padded")) pads.add((String) k);
            defaults.put(t.getName(), def);
            padded.put(t.getName(), pads);
            return;
        }
        Map<String, Map<Object, Integer>> counts = new HashMap<>();
        Map<String, int[]> pad = new HashMap<>();  // [nonblank, fullwidth]
        for (Row r : t)
            for (Column c : t.getColumns()) {
                Object v = r.get(c.getName());
                counts.computeIfAbsent(c.getName(), k -> new HashMap<>()).merge(v == null ? NULL : v, 1, Integer::sum);
                if (c.getType() == DataType.TEXT && v instanceof String s && !s.isBlank()) {
                    int[] p = pad.computeIfAbsent(c.getName(), k -> new int[2]);
                    p[0]++;
                    if (s.length() == c.getLengthInUnits()) p[1]++;
                }
            }
        Map<String, Object> def = new HashMap<>();
        Set<String> pads = new HashSet<>();
        for (Column c : t.getColumns()) {
            if (c.isAutoNumber()) continue;
            Map<Object, Integer> cnt = counts.get(c.getName());
            Object best = null;
            if (cnt != null) {
                Object top = Collections.max(cnt.entrySet(), Map.Entry.comparingByValue()).getKey();
                if (top != NULL && blank(top)) best = top;
                else if (top != NULL && c.getType() == DataType.TEXT) best = null;
                else if (top != NULL) best = zero(c);
            }
            if (best != null) def.put(c.getName(), best);
            int[] p = pad.get(c.getName());
            if (p != null && p[0] > 0 && p[1] * 2 >= p[0]) pads.add(c.getName());
        }
        defaults.put(t.getName(), def);
        padded.put(t.getName(), pads);
    }

    static final Object NULL = new Object();

    static boolean blank(Object v) {
        if (v instanceof String s) return s.isBlank();
        if (v instanceof Number n) return n.doubleValue() == 0;
        if (v instanceof Boolean b) return !b;
        return false;
    }

    static Object zero(Column c) {
        switch (c.getType()) {
            case BOOLEAN: return false;
            case BYTE: return (byte) 0;
            case INT: return (short) 0;
            case LONG: return 0;
            case FLOAT: return 0f;
            case DOUBLE: return 0d;
            default: return null;
        }
    }

    static Map<String, Object> base(String table, Table t) {
        return new HashMap<>(defaults.getOrDefault(table, Map.of()));
    }

    /** Text put that mimics MM: truncate to width, pad to width when MM pads that column. */
    static void put(Map<String, Object> r, Table t, String col, String v) {
        Column c = t.getColumn(col);
        if (c == null) return;
        v = v == null ? "" : v.trim();
        int w = c.getLengthInUnits();
        if (v.length() > w) v = v.substring(0, w);
        if (v.isEmpty()) {          // MM leaves unused text as its usual blank (' ', padding) or null
            if (!r.containsKey(col)) r.put(col, null);
            return;
        }
        if (padded.getOrDefault(t.getName(), Set.of()).contains(col)) v = String.format("%-" + w + "s", v);
        r.put(col, v);
    }

    static void putRaw(Map<String, Object> r, Table t, String col, String v) {
        Column c = t.getColumn(col);
        if (c == null) return;
        int w = c.getLengthInUnits();
        r.put(col, v.length() > w ? v.substring(0, w) : v);
    }

    static void seed(Map<String, Object> r, Table t, JSONObject e) {
        put(r, t, "ActSeed_course", e.optString("course", "Y"));
        put(r, t, "ConvSeed_course", e.optString("conv_course", e.optString("course", "Y")));
        r.put("ActualSeed_time", (float) e.optDouble("seed", 0));
        r.put("ConvSeed_time", (float) e.optDouble("conv_seed", e.optDouble("seed", 0)));
    }
}
