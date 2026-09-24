# FUNCTION 1: Get and check user input
def get_valid_input():
    entry = input("Enter stock quantity or enter 'quit' to exit: ")

    if entry == "quit":
        return "quit"

    elif entry.startswith("-"):
        print("Error: negative stock quantity is not allowed")
        return None

    elif not entry.isdigit():
        print("Error: Please enter valid integer")
        return None

    else:
        return int(entry)


# FUNCTION 2: Add delivery to inventory
def process_delivery(current_total, new_value):
    return current_total + new_value


# FUNCTION 3: Calculate 10% tax
def calculate_tax(amount):
    return amount * 0.10


# FUNCTION 4: Print final report
def generate_report(total_deliveries, failed_attempts):
    print("Total Deliveries Processed:", total_deliveries)
    print("Number of Failed/Rejected entries:", failed_attempts)


inventory = 0
failed = 0
deliveries = 0

while True:
    enteredquantity = get_valid_input()

    if enteredquantity == "quit":
        print(generate_report(deliveries, failed))
        break

    elif enteredquantity is None:
        failed += 1

    else:
        inventory = process_delivery(inventory, enteredquantity)
        tax = calculate_tax(enteredquantity)
        deliveries += 1

        if inventory > 500:
                    print("Alert! stock inventory exceeds over 500 units")

        else:             
        
            
            print("Tax for this delivery:", tax)
            print("Delivery Amount: $", f"{enteredquantity:.2f}")
            print("Total amount to be paid: $", f"{inventory + calculate_tax(inventory):.2f}", "\n")
            
            
    

   
           
