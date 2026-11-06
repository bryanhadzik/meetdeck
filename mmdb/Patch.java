import com.healthmarketscience.jackcess.*;
import org.json.*;
import java.io.File;
import java.nio.file.*;
import java.util.*;

/** java Patch db.mdb patches.json  -  [{table, match:{col:val}, set:{col:val}}]; each match must hit exactly one row. */
public class Patch {
    public static void main(String[] a) throws Exception {
        JSONArray ps = new JSONArray(Files.readString(Paths.get(a[1])));
        try (Database db = new DatabaseBuilder(new File(a[0])).open()) {
            for (int i = 0; i < ps.length(); i++) {
                JSONObject p = ps.getJSONObject(i);
                Table t = db.getTable(p.getString("table"));
                JSONObject m = p.getJSONObject("match"), s = p.getJSONObject("set");
                Cursor c = CursorBuilder.createCursor(t);
                int hits = 0;
                while (c.moveToNextRow()) {
                    Row r = c.getCurrentRow();
                    boolean ok = true;
                    for (String k : m.keySet()) {
                        Object v = r.get(k);
                        if (v == null || !v.toString().trim().equals(m.get(k).toString())) { ok = false; break; }
                    }
                    if (!ok) continue;
                    hits++;
                    Map<String, Object> u = new HashMap<>();
                    for (String k : s.keySet()) {
                        Column col = t.getColumn(k);
                        Object v = s.get(k);
                        switch (col.getType()) {
                            case FLOAT: u.put(k, ((Number) v).floatValue()); break;
                            case DOUBLE: u.put(k, ((Number) v).doubleValue()); break;
                            case INT: u.put(k, ((Number) v).shortValue()); break;
                            case LONG: u.put(k, ((Number) v).intValue()); break;
                            default: u.put(k, v == JSONObject.NULL ? null : v.toString());
                        }
                    }
                    c.updateCurrentRowFromMap(u);
                }
                System.out.println((hits == 1 ? "OK   " : "FAIL ") + hits + " row(s): " + m);
                if (hits != 1) System.exit(1);
            }
        }
    }
}
