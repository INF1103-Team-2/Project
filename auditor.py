inventory = 0
failed = 0
enteredquantity = 0

while True:
    entry = input("Enter stock quantity or enter 'quit' to exit: ")
    if entry == "quit":
        break

    elif entry.startswith("-"):
        print("Error: negative stock quantity is not allowed")
        failed += 1

    elif not entry.isdigit():
        print("Error: Please enter valid integer")
        failed += 1

    else:
        enteredquantity += int(entry)
        inventory = inventory + enteredquantity

    if inventory > 500:
        print("Alert! stock inventory exceeds over 500 units")
        break

    print("Total Units Processed:", inventory)
    print("Number of Failed/Rejected entries:", failed)


