import com.healthmarketscience.jackcess.*;
import java.io.File;
import java.util.*;

public class Dump {
    public static void main(String[] a) throws Exception {
        Database db = new DatabaseBuilder(new File(a[0])).setReadOnly(true).open();
        System.out.println("FORMAT " + db.getFileFormat() + " pwd? " + db.getDatabasePassword());
        int rows = a.length > 1 ? Integer.parseInt(a[1]) : 2;
        Set<String> only = new HashSet<>();
        for (int i = 2; i < a.length; i++) only.add(a[i]);
        for (String t : db.getTableNames()) {
            if (!only.isEmpty() && !only.contains(t)) continue;
            Table tb = db.getTable(t);
            System.out.println("\n== " + t + " rows=" + tb.getRowCount());
            StringBuilder sb = new StringBuilder();
            for (Column c : tb.getColumns())
                sb.append(c.getName()).append(':').append(c.getType()).append(c.isAutoNumber() ? "(auto)" : "")
                  .append(c.getType() == DataType.TEXT ? "(" + c.getLengthInUnits() + ")" : "").append("  ");
            System.out.println(sb);
            for (Index ix : tb.getIndexes())
                System.out.println("  idx " + ix.getName() + (ix.isPrimaryKey() ? " PK" : "") + (ix.isUnique() ? " U" : "") + " " + ix.getColumns());
            int n = 0;
            for (Row r : tb) {
                if (n++ >= rows) break;
                StringBuilder rb = new StringBuilder("  ");
                for (Map.Entry<String, Object> e : r.entrySet()) {
                    Object v = e.getValue();
                    if (v == null || "".equals(v) || Integer.valueOf(0).equals(v) || Short.valueOf((short)0).equals(v) || Boolean.FALSE.equals(v) || Double.valueOf(0).equals(v) || Float.valueOf(0).equals(v)) continue;
                    rb.append(e.getKey()).append('=').append(v).append(" | ");
                }
                System.out.println(rb);
            }
        }
    }
}
