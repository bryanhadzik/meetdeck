import com.healthmarketscience.jackcess.*;
import com.sun.net.httpserver.*;
import org.json.*;

import java.io.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.Executors;

/**
 * Long-running Meet Manager database service (localhost only).
 *   POST /read   {db, tables:[...]}                 -> {tables:{name:{columns:[...], rows:[...]}}}
 *   POST /apply  {db, ops:[{op, table, match, set|row}]} -> {results:[...]}
 *   POST /close  {db}
 * One request at a time; databases stay open between requests and are flushed after every write.
 */
public class Svc {
    static final Map<String, Database> OPEN = new HashMap<>();

    public static void main(String[] a) throws Exception {
        Path prof = Paths.get(System.getProperty("mm.profile", "/opt/mmdb/profile.json"));
        if (Files.exists(prof)) Builder.profile = new JSONObject(Files.readString(prof));
        int port = a.length > 0 ? Integer.parseInt(a[0]) : 8765;
        HttpServer s = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        s.setExecutor(Executors.newSingleThreadExecutor());
        s.createContext("/ping", ex -> reply(ex, 200, new JSONObject().put("ok", true)));
        s.createContext("/read", ex -> handle(ex, Svc::read));
        s.createContext("/apply", ex -> handle(ex, Svc::apply));
        s.createContext("/close", ex -> handle(ex, b -> { close(b.getString("db")); return new JSONObject().put("ok", true); }));
        s.start();
        System.out.println("mmdb service on " + port);
    }

    interface H { JSONObject run(JSONObject body) throws Exception; }

    static void handle(HttpExchange ex, H h) throws IOException {
        try {
            JSONObject body = new JSONObject(new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            reply(ex, 200, h.run(body));
        } catch (Exception e) {
            StringWriter sw = new StringWriter();
            e.printStackTrace(new PrintWriter(sw));
            System.err.println(sw);
            reply(ex, 500, new JSONObject().put("error", e.getClass().getSimpleName() + ": " + e.getMessage()));
        }
    }

    static void reply(HttpExchange ex, int code, JSONObject o) throws IOException {
        byte[] b = o.toString().getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(code, b.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(b); }
    }

    static Database db(String path) throws IOException {
        Database d = OPEN.get(path);
        if (d == null) {
            d = new DatabaseBuilder(new File(path)).setAutoSync(false).open();
            OPEN.put(path, d);
        }
        return d;
    }

    static void close(String path) throws IOException {
        Database d = OPEN.remove(path);
        if (d != null) d.close();
    }

    // ---- read -------------------------------------------------------------------
    static JSONObject read(JSONObject b) throws Exception {
        Database d = db(b.getString("db"));
        JSONObject out = new JSONObject();
        JSONArray names = b.optJSONArray("tables");
        Collection<String> want = new ArrayList<>();
        if (names == null) want.addAll(d.getTableNames()); else for (Object n : names) want.add((String) n);
        for (String tn : want) {
            Table t = d.getTable(tn);
            if (t == null) continue;
            JSONArray cols = new JSONArray();
            for (Column c : t.getColumns())
                cols.put(new JSONObject().put("name", c.getName()).put("type", c.getType().name()).put("auto", c.isAutoNumber())
                        .put("len", c.getType() == DataType.TEXT ? c.getLengthInUnits() : 0));
            JSONArray rows = new JSONArray();
            for (Row r : t) {
                JSONObject o = new JSONObject();
                for (Column c : t.getColumns()) o.put(c.getName(), out(c, r.get(c.getName())));
                rows.put(o);
            }
            out.put(tn, new JSONObject().put("columns", cols).put("rows", rows));
        }
        return new JSONObject().put("tables", out);
    }

    static Object out(Column c, Object v) {
        if (v == null) return JSONObject.NULL;
        if (v instanceof Float f) return Math.round(f * 100.0) / 100.0;
        if (v instanceof Double dd) return Math.round(dd * 100.0) / 100.0;
        if (v instanceof LocalDateTime t) return t.toString();
        if (v instanceof Date t) return t.toInstant().toString();
        if (v instanceof java.math.BigDecimal bd) return bd.doubleValue();
        if (v instanceof byte[]) return JSONObject.NULL;
        return v;
    }

    // ---- write ------------------------------------------------------------------
    static JSONObject apply(JSONObject b) throws Exception {
        Database d = db(b.getString("db"));
        JSONArray res = new JSONArray();
        try {
            for (Object o : b.getJSONArray("ops")) {
                JSONObject op = (JSONObject) o;
                Table t = d.getTable(op.getString("table"));
                if (t == null) throw new IllegalArgumentException("no table " + op.getString("table"));
                switch (op.getString("op")) {
                    case "update" -> res.put(new JSONObject().put("count", update(t, op.optJSONObject("match"), op.getJSONObject("set"))));
                    case "delete" -> res.put(new JSONObject().put("count", delete(t, op.getJSONObject("match"))));
                    case "insert" -> res.put(new JSONObject().put("row", insert(t, op.getJSONObject("row"))));
                    default -> throw new IllegalArgumentException("bad op " + op.getString("op"));
                }
            }
        } finally {
            d.flush();
        }
        return new JSONObject().put("results", res);
    }

    static boolean matches(Table t, Row r, JSONObject m) {
        if (m == null) return true;
        for (String k : m.keySet()) {
            Object want = m.get(k), have = r.get(k);
            if (want == JSONObject.NULL) { if (have != null) return false; continue; }
            if (have == null) return false;
            if (have instanceof Number hn && want instanceof Number wn) {
                if (Math.abs(hn.doubleValue() - wn.doubleValue()) > 0.0001) return false;
            } else if (have instanceof Boolean hb) {
                if (hb != (want instanceof Boolean wb ? wb : Boolean.parseBoolean(want.toString()))) return false;
            } else if (!have.toString().trim().equals(want.toString().trim())) return false;
        }
        return true;
    }

    static int update(Table t, JSONObject match, JSONObject set) throws IOException {
        if (LEARNED.add(t.getDatabase().getFile() + "|" + t.getName())) Builder.learn(t);
        Cursor c = CursorBuilder.createCursor(t);
        int n = 0;
        while (c.moveToNextRow()) {
            Row r = c.getCurrentRow();
            if (!matches(t, r, match)) continue;
            Map<String, Object> m = new HashMap<>();
            for (String k : set.keySet()) put(t, m, k, set.get(k));
            c.updateCurrentRowFromMap(m);
            n++;
        }
        return n;
    }

    static int delete(Table t, JSONObject match) throws IOException {
        if (match == null || match.isEmpty()) throw new IllegalArgumentException("delete needs a match");
        Cursor c = CursorBuilder.createCursor(t);
        int n = 0;
        while (c.moveToNextRow()) if (matches(t, c.getCurrentRow(), match)) { c.deleteCurrentRow(); n++; }
        return n;
    }

    static final Set<String> LEARNED = new HashSet<>();

    static JSONObject insert(Table t, JSONObject row) throws IOException {
        if (LEARNED.add(t.getDatabase().getFile() + "|" + t.getName())) Builder.learn(t);
        Map<String, Object> m = Builder.base(t.getName(), t);
        for (String k : row.keySet()) put(t, m, k, row.get(k));
        t.addRowFromMap(m);
        JSONObject o = new JSONObject();
        for (Column c : t.getColumns()) if (m.containsKey(c.getName())) o.put(c.getName(), out(c, m.get(c.getName())));
        return o;   // addRowFromMap fills autonumber values back into the map
    }

    /** Convert a JSON value to the column's type. Text keeps MM's padding rules (via Builder.put). */
    static void put(Table t, Map<String, Object> m, String col, Object v) {
        Column c = t.getColumn(col);
        if (c == null) throw new IllegalArgumentException("no column " + t.getName() + "." + col);
        if (v == JSONObject.NULL || v == null) { m.put(col, null); return; }
        switch (c.getType()) {
            case TEXT, MEMO -> {
                String s = v.toString();
                if (s.isEmpty()) { m.put(col, null); return; }
                if (s.isBlank()) { m.put(col, s); return; }
                m.remove(col);
                Builder.put(m, t, col, s);
            }
            case BOOLEAN -> m.put(col, v instanceof Boolean bb ? bb : Boolean.parseBoolean(v.toString()));
            case BYTE -> m.put(col, (byte) num(v));
            case INT -> m.put(col, (short) Math.round(num(v)));
            case LONG -> m.put(col, (int) Math.round(num(v)));
            case FLOAT -> m.put(col, (float) num(v));
            case DOUBLE -> m.put(col, num(v));
            case MONEY, NUMERIC -> m.put(col, new java.math.BigDecimal(v.toString()));
            case SHORT_DATE_TIME -> {
                String s = v.toString();
                m.put(col, s.length() == 10 ? LocalDate.parse(s).atStartOfDay() : LocalDateTime.parse(s.replace("Z", "")));
            }
            default -> m.put(col, v);
        }
    }

    static double num(Object v) {
        return v instanceof Number n ? n.doubleValue() : Double.parseDouble(v.toString().trim().isEmpty() ? "0" : v.toString());
    }
}
