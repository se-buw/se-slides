import java.awt.image.BufferedImage;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import javafx.application.Application;
import javafx.application.Platform;
import javafx.event.Event;
import javafx.geometry.Rectangle2D;
import javafx.scene.Node;
import javafx.scene.SnapshotParameters;
import javafx.scene.paint.Color;
import javafx.scene.transform.Transform;
import javafx.scene.Parent;
import javafx.scene.Scene;
import javafx.scene.control.ButtonBase;
import javafx.scene.control.ComboBox;
import javafx.scene.control.ListView;
import javafx.scene.control.SelectionMode;
import javafx.scene.control.Slider;
import javafx.scene.control.TextInputControl;
import javafx.scene.image.PixelReader;
import javafx.scene.image.WritableImage;
import javafx.scene.input.KeyCode;
import javafx.scene.input.KeyEvent;
import javafx.scene.input.MouseButton;
import javafx.scene.input.MouseEvent;
import javafx.stage.Stage;
import javafx.stage.Window;

/**
 * Takes screenshots of JavaFX programs for slides. Started by BuildCode.java, which compiles it
 * together with the lecture's code; needs JavaFX on the module path.
 *
 * Usage: java --module-path ... --add-modules ... -cp classes FxShots spec.txt outDir [name ...]
 *
 * One line per screenshot in spec.txt ('#' starts a comment, values with blanks in double quotes):
 *
 *   name  MainClass  action...
 *
 * Actions are carried out in the order written; each is followed by a short pause:
 *   size=WxH           resize the scene (the window grows by its decoration)
 *   wait=ms            wait, e.g. for an animation (default: 400 ms after start, 300 ms before the shot)
 *   fire="text"        fire the button, check box or radio button with this text
 *   text="abc"         set the text of the first text field or text area
 *   slider=0.6         set the first slider (in its own range)
 *   select="A,B"       select items (by toString) in the first combo box, else in the first list view
 *   type="Ab"          type characters: key pressed, typed and released events to the focused node
 *   key=ESCAPE         press and release a key (a KeyCode name)
 *   click=x,y[,shift|secondary]   mouse press, release and click at scene position (x, y)
 *   drag=x1,y1,x2,y2[,shift]      press at 1, drag to 2, release
 *
 * Writes name.png (2x pixels) for the primary window and name-2.png, ... for further windows.
 */
public class FxShots {

    static final double SCALE = 2;

    record Shot(String name, String mainClass, List<String[]> actions) {}

    public static void main(String[] args) throws Exception {
        Path spec = Path.of(args[0]);
        Path outDir = Path.of(args[1]);
        List<String> wanted = Arrays.asList(args).subList(2, args.length);
        Files.createDirectories(outDir);
        List<Shot> shots = parse(spec);
        Platform.setImplicitExit(false);
        Platform.startup(() -> { });
        int failed = 0;
        for (Shot shot : shots) {
            if (!wanted.isEmpty() && !wanted.contains(shot.name())) continue;
            try {
                take(shot, outDir);
                System.out.println("shot " + shot.name());
            } catch (Throwable t) {
                System.out.println(shot.name() + ": error: " + t);
                failed++;
            }
        }
        Platform.exit();
        System.exit(failed == 0 ? 0 : 1);
    }

    // ---------------------------------------------------------------- spec

    static List<Shot> parse(Path spec) throws Exception {
        List<Shot> shots = new ArrayList<>();
        for (String line : Files.readAllLines(spec)) {
            line = line.strip();
            if (line.isEmpty() || line.startsWith("#")) continue;
            List<String> words = tokens(line);
            List<String[]> actions = new ArrayList<>();
            for (String w : words.subList(2, words.size())) {
                int eq = w.indexOf('=');
                actions.add(new String[] {w.substring(0, eq), w.substring(eq + 1)});
            }
            shots.add(new Shot(words.get(0), words.get(1), actions));
        }
        return shots;
    }

    /** Splits at blanks; key="a b" keeps the blank inside the quotes and drops the quotes. */
    static List<String> tokens(String line) {
        List<String> out = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        boolean quoted = false;
        for (char c : line.toCharArray()) {
            if (c == '"') quoted = !quoted;
            else if (Character.isWhitespace(c) && !quoted) {
                if (!cur.isEmpty()) out.add(cur.toString());
                cur.setLength(0);
            } else cur.append(c);
        }
        if (!cur.isEmpty()) out.add(cur.toString());
        return out;
    }

    // ---------------------------------------------------------------- one shot

    static void take(Shot shot, Path outDir) throws Exception {
        Application app = fx(() -> {
            Application a = (Application) Class.forName(shot.mainClass()).getDeclaredConstructor().newInstance();
            Stage stage = new Stage();
            a.start(stage);
            primary = stage;
            return a;
        });
        try {
            pause(400);
            for (String[] action : shot.actions()) {
                String value = action[1];
                switch (action[0]) {
                    case "wait" -> pause(Long.parseLong(value));
                    default -> fx(() -> { act(action[0], value); return null; });
                }
                pause(150);
            }
            pause(300);
            List<Stage> windows = fx(FxShots::shownStages);
            int n = 0;
            for (Stage stage : windows) {
                BufferedImage image = fx(() -> snapshot(stage.getScene()));
                String file = shot.name() + (n == 0 ? "" : "-" + (n + 1)) + ".png";
                javax.imageio.ImageIO.write(image, "png", outDir.resolve(file).toFile());
                n++;
            }
            if (n == 0) throw new IllegalStateException("no window is showing");
        } finally {
            fx(() -> {
                app.stop();
                for (Window w : List.copyOf(Window.getWindows())) w.hide();
                return null;
            });
        }
    }

    static Stage primary;

    static List<Stage> shownStages() {
        List<Stage> stages = new ArrayList<>();
        if (primary != null && primary.isShowing()) stages.add(primary);
        for (Window w : Window.getWindows()) {
            if (w instanceof Stage s && s != primary && s.isShowing() && s.getScene() != null) stages.add(s);
        }
        return stages;
    }

    static BufferedImage snapshot(Scene scene) {
        scene.getRoot().applyCss();
        SnapshotParameters params = new SnapshotParameters();
        params.setTransform(Transform.scale(SCALE, SCALE));
        params.setViewport(new Rectangle2D(0, 0, scene.getWidth() * SCALE, scene.getHeight() * SCALE));
        params.setFill(scene.getFill() instanceof Color c ? c : Color.WHITE);
        WritableImage img = scene.getRoot().snapshot(params, null);
        PixelReader reader = img.getPixelReader();
        int w = (int) img.getWidth(), h = (int) img.getHeight();
        BufferedImage out = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) out.setRGB(x, y, reader.getArgb(x, y));
        }
        return out;
    }

    // ---------------------------------------------------------------- actions (on the FX thread)

    static void act(String kind, String value) {
        List<Stage> stages = shownStages();
        Scene scene = stages.get(stages.size() - 1).getScene();   // the window opened last, e.g. a tool window
        Scene first = stages.get(0).getScene();
        switch (kind) {
            case "size" -> {
                String[] wh = value.split("x");
                Stage s = stages.get(0);
                s.setWidth(Double.parseDouble(wh[0]) + (s.getWidth() - first.getWidth()));
                s.setHeight(Double.parseDouble(wh[1]) + (s.getHeight() - first.getHeight()));
            }
            case "fire" -> {
                for (Stage s : stages) {
                    for (Node n : all(s.getScene().getRoot())) {
                        if (n instanceof ButtonBase b && value.equals(b.getText())) { b.fire(); return; }
                    }
                }
                throw new IllegalArgumentException("no button with text \"" + value + "\"");
            }
            case "text" -> ((TextInputControl) find(first, TextInputControl.class)).setText(value);
            case "slider" -> {
                Slider s = find(first, Slider.class);
                s.setValue(s.getMin() + Double.parseDouble(value) * (s.getMax() - s.getMin()));
            }
            case "select" -> select(first, value.split(","));
            case "type" -> {
                for (char c : value.toCharArray()) typeChar(first, c);
            }
            case "key" -> {
                KeyCode code = KeyCode.valueOf(value);
                key(first, KeyEvent.KEY_PRESSED, code, "", "", false);
                key(first, KeyEvent.KEY_RELEASED, code, "", "", false);
            }
            case "click", "drag" -> mouse(first, kind, value.split(","));
            default -> throw new IllegalArgumentException("unknown action " + kind);
        }
    }

    static void select(Scene scene, String[] items) {
        Node combo = scene.getRoot().lookup(".combo-box");
        if (combo instanceof ComboBox<?> cb) {
            selectIn(cb, items[0]);
            return;
        }
        @SuppressWarnings("unchecked")
        ListView<Object> list = (ListView<Object>) find(scene, ListView.class);
        list.getSelectionModel().setSelectionMode(SelectionMode.MULTIPLE);
        for (String item : items) {
            for (Object o : list.getItems()) {
                if (o.toString().strip().equals(item.strip())) list.getSelectionModel().select(o);
            }
        }
    }

    @SuppressWarnings("unchecked")
    static void selectIn(ComboBox<?> cb, String item) {
        ComboBox<Object> box = (ComboBox<Object>) cb;
        for (Object o : box.getItems()) {
            if (o.toString().equals(item)) { box.setValue(o); return; }
        }
        throw new IllegalArgumentException("no item " + item);
    }

    static void typeChar(Scene scene, char c) {
        String s = String.valueOf(c);
        KeyCode code = Character.isLetterOrDigit(c) ? KeyCode.getKeyCode(s.toUpperCase()) : KeyCode.UNDEFINED;
        if (code == null) code = KeyCode.UNDEFINED;
        boolean shift = Character.isUpperCase(c);
        key(scene, KeyEvent.KEY_PRESSED, code, s.toLowerCase(), "", shift);
        key(scene, KeyEvent.KEY_TYPED, KeyCode.UNDEFINED, s, "", shift);
        key(scene, KeyEvent.KEY_RELEASED, code, s.toLowerCase(), "", shift);
    }

    static void key(Scene scene, javafx.event.EventType<KeyEvent> type, KeyCode code, String text, String unused, boolean shift) {
        Node focus = scene.getFocusOwner();
        Object target = focus != null ? focus : scene;
        boolean typed = type == KeyEvent.KEY_TYPED;
        Event.fireEvent((javafx.event.EventTarget) target,
                new KeyEvent(type, typed ? text : KeyEvent.CHAR_UNDEFINED, typed ? "" : text, code, shift, false, false, false));
    }

    static void mouse(Scene scene, String kind, String[] v) {
        double x = Double.parseDouble(v[0]), y = Double.parseDouble(v[1]);
        boolean drag = kind.equals("drag");
        String mod = v[v.length - 1];
        boolean shift = mod.equals("shift");
        MouseButton button = mod.equals("secondary") ? MouseButton.SECONDARY : MouseButton.PRIMARY;
        Node target = at(scene.getRoot(), x, y);
        fireMouse(target, MouseEvent.MOUSE_PRESSED, x, y, button, shift, 1);
        if (drag) {
            double x2 = Double.parseDouble(v[2]), y2 = Double.parseDouble(v[3]);
            fireMouse(target, MouseEvent.MOUSE_DRAGGED, x2, y2, button, shift, 1);
            fireMouse(target, MouseEvent.MOUSE_RELEASED, x2, y2, button, shift, 1);
        } else {
            fireMouse(target, MouseEvent.MOUSE_RELEASED, x, y, button, shift, 1);
            fireMouse(target, MouseEvent.MOUSE_CLICKED, x, y, button, shift, 1);
        }
    }

    static void fireMouse(Node target, javafx.event.EventType<MouseEvent> type, double x, double y,
                          MouseButton button, boolean shift, int clicks) {
        boolean down = type != MouseEvent.MOUSE_RELEASED && type != MouseEvent.MOUSE_CLICKED;
        Event.fireEvent(target, new MouseEvent(type, x, y, x, y, button, clicks, shift, false, false, false,
                down && button == MouseButton.PRIMARY, false, down && button == MouseButton.SECONDARY,
                false, false, true, null));
    }

    /** The topmost visible node at the scene position (x, y); a mouse event bubbles up from there. */
    static Node at(Node root, double x, double y) {
        if (root instanceof Parent p) {
            List<Node> children = p.getChildrenUnmodifiable();
            for (int i = children.size() - 1; i >= 0; i--) {
                Node c = children.get(i);
                if (!c.isVisible() || c.isMouseTransparent()) continue;
                Node hit = at(c, x, y);
                if (hit != null) return hit;
            }
        }
        var local = root.sceneToLocal(x, y);
        if (local != null && root.contains(local)) return root;
        return null;
    }

    // ---------------------------------------------------------------- helpers

    static List<Node> all(Node n) {
        List<Node> out = new ArrayList<>();
        out.add(n);
        if (n instanceof Parent p) for (Node c : p.getChildrenUnmodifiable()) out.addAll(all(c));
        return out;
    }

    @SuppressWarnings("unchecked")
    static <T> T find(Scene scene, Class<?> type) {
        for (Node n : all(scene.getRoot())) if (type.isInstance(n)) return (T) n;
        throw new IllegalArgumentException("no " + type.getSimpleName() + " in the window");
    }

    static <T> T fx(Callable<T> job) throws Exception {
        CompletableFuture<T> f = new CompletableFuture<>();
        Platform.runLater(() -> {
            try { f.complete(job.call()); } catch (Throwable t) { f.completeExceptionally(t); }
        });
        try {
            return f.get(30, TimeUnit.SECONDS);
        } catch (java.util.concurrent.ExecutionException e) {
            throw e.getCause() instanceof Exception ex ? ex : e;
        }
    }

    static void pause(long ms) throws InterruptedException {
        Thread.sleep(ms);
    }
}
