import java.io.IOException;
import java.io.InputStream;
import java.io.PrintStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Runs the main method of a class so that the recorded output looks like a
 * console session: every input line is echoed at the moment the program reads it.
 *
 * Usage: java -cp <classes>:<this> EchoRunner MainClass [args...] < input
 */
public class EchoRunner {

    /** Hands out stdin one line per read and echoes it to stdout. */
    static final class EchoingInput extends InputStream {
        private final InputStream in;
        private final PrintStream echo;

        EchoingInput(InputStream in, PrintStream echo) {
            this.in = in;
            this.echo = echo;
        }

        @Override
        public int read() throws IOException {
            byte[] one = new byte[1];
            int n = read(one, 0, 1);
            return n <= 0 ? -1 : one[0] & 0xff;
        }

        @Override
        public int read(byte[] b, int off, int len) throws IOException {
            int n = 0;
            while (n < len) {
                int c = in.read();
                if (c < 0) break;
                if (c == '\r') continue;
                b[off + n++] = (byte) c;
                if (c == '\n') break;
            }
            if (n == 0) return -1;
            echo.write(b, off, n);
            echo.flush();
            return n;
        }

        @Override
        public int available() {
            return 0; // make readers return after each line
        }
    }

    public static void main(String[] args) throws Exception {
        PrintStream out = System.out;
        System.setIn(new EchoingInput(System.in, out));
        Class<?> target = Class.forName(args[0]);
        Method main = target.getMethod("main", String[].class);
        try {
            main.invoke(null, (Object) Arrays.copyOfRange(args, 1, args.length));
        } catch (InvocationTargetException e) {
            out.flush();
            printLikeJvm(e.getCause());
            System.exit(1);
        }
        out.flush();
    }

    /** Prints an uncaught exception as the JVM would, without the reflection frames. */
    private static void printLikeJvm(Throwable t) {
        List<StackTraceElement> frames = new ArrayList<>();
        for (StackTraceElement f : t.getStackTrace()) {
            String c = f.getClassName();
            if (c.equals(EchoRunner.class.getName()) || c.startsWith("jdk.internal.reflect.")
                    || c.startsWith("java.lang.reflect.")) {
                break;
            }
            frames.add(f);
        }
        t.setStackTrace(frames.toArray(new StackTraceElement[0]));
        System.err.print("Exception in thread \"main\" ");
        t.printStackTrace();
        System.err.flush();
    }
}
