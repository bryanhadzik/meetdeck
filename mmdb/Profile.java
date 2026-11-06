import com.healthmarketscience.jackcess.*;
import java.io.File;
import java.util.*;

/** Prints, per column, the distinct values seen (with counts) - to learn MM's defaults. */
public class Profile {
    public static void main(String[] a) throws Exception {
        Database db = new DatabaseBuilder(new File(a[0])).setReadOnly(true).open();
        for (int i = 1; i < a.length; i++) {
            Table t = db.getTable(a[i]);
            System.out.println("\n== " + a[i] + " (" + t.getRowCount() + ")");
            Map<String, Map<String, Integer>> m = new LinkedHashMap<>();
            for (Column c : t.getColumns()) m.put(c.getName(), new LinkedHashMap<>());
            for (Row r : t)
                for (Column c : t.getColumns()) {
                    Object v = r.get(c.getName());
                    String k = v == null ? "<null>" : (v instanceof String ? "'" + v + "'" : v.toString());
                    m.get(c.getName()).merge(k, 1, Integer::sum);
                }
            for (Map.Entry<String, Map<String, Integer>> e : m.entrySet()) {
                Map<String, Integer> d = e.getValue();
                String s = d.size() > 6 ? d.size() + " distinct, e.g. " + d.keySet().iterator().next() : d.toString();
                System.out.println("  " + e.getKey() + ": " + s);
            }
        }
    }
}
