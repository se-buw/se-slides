import java.util.Scanner;

/** Greets the user. */
public class Hello {
    public static void main(String[] args) {
        Scanner input = new Scanner(System.in);
        // region greet
        System.out.print("Your name: ");
        String name = input.nextLine();
        System.out.println("Hello, " + name + "!");
        // endregion
    }
}
