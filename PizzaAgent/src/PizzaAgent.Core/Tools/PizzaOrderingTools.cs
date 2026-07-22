using System.ComponentModel;
using System.Text;
using PizzaAgent.Core.Menu;
using PizzaAgent.Core.Models;

namespace PizzaAgent.Core.Tools;

public class PizzaOrderingTools
{
    private readonly Order _order = new();
    private readonly Action<string> _log;

    public PizzaOrderingTools(Action<string>? log = null)
    {
        _log = log ?? (_ => { });
    }

    [Description("Get available pizza options from the menu, optionally filtered by dietary preference")]
    public string GetMenuOptions(
        [Description("Filter by dietary preference: 'veg' for vegetarian only, 'non-veg' for non-vegetarian only, 'all' for the full menu")] string preference = "all")
    {
        _log($"GetMenuOptions(preference: \"{preference}\")");

        var pizzas = preference.ToLower() switch
        {
            "veg" => PizzaMenu.GetByCategory(PizzaCategory.Veg),
            "non-veg" or "nonveg" => PizzaMenu.GetByCategory(PizzaCategory.NonVeg),
            _ => PizzaMenu.All.AsEnumerable()
        };

        var sb = new StringBuilder();
        var grouped = pizzas.GroupBy(p => p.Category);

        foreach (var group in grouped)
        {
            sb.AppendLine(group.Key == PizzaCategory.Veg ? "VEGETARIAN OPTIONS:" : "NON-VEGETARIAN OPTIONS:");
            foreach (var pizza in group)
            {
                sb.AppendLine($"  - {pizza.Name}: {pizza.Description}");
                sb.AppendLine($"    Small £{pizza.Prices[PizzaSize.Small]:F2} | Medium £{pizza.Prices[PizzaSize.Medium]:F2} | Large £{pizza.Prices[PizzaSize.Large]:F2}");
            }
            sb.AppendLine();
        }

        sb.AppendLine("Note: One large pizza serves ~3 people, medium serves ~2, small serves 1.");
        return sb.ToString();
    }

    [Description("Add a pizza to the current order. Returns confirmation or an error if the pizza is not found.")]
    public string AddToOrder(
        [Description("Exact name of the pizza as shown on the menu")] string pizzaName,
        [Description("Size of the pizza: 'small', 'medium', or 'large'")] string size,
        [Description("Number of pizzas to add (defaults to 1)")] int quantity = 1)
    {
        _log($"AddToOrder(pizzaName: \"{pizzaName}\", size: \"{size}\", quantity: {quantity})");

        var pizza = PizzaMenu.FindByName(pizzaName);
        if (pizza is null)
            return $"Sorry, '{pizzaName}' is not on our menu. Use GetMenuOptions to see available pizzas.";

        if (!Enum.TryParse<PizzaSize>(size, ignoreCase: true, out var pizzaSize))
            return "Invalid size. Please use 'small', 'medium', or 'large'.";

        if (quantity < 1 || quantity > 20)
            return "Quantity must be between 1 and 20.";

        var existing = _order.Items.FirstOrDefault(i =>
            i.Pizza.Name == pizza.Name && i.Size == pizzaSize);

        if (existing is not null)
        {
            existing.Quantity += quantity;
            _order.Status = OrderStatus.Building;
            return $"Updated: {existing.Quantity}x {pizza.Name} ({size}) — £{existing.UnitPrice:F2} each.";
        }

        _order.Items.Add(new OrderItem { Pizza = pizza, Size = pizzaSize, Quantity = quantity });
        _order.Status = OrderStatus.Building;
        return $"Added {quantity}x {pizza.Name} ({size}) — £{pizza.Prices[pizzaSize]:F2} each.";
    }

    [Description("Remove a pizza from the current order")]
    public string RemoveFromOrder(
        [Description("Exact name of the pizza to remove")] string pizzaName,
        [Description("Size of the pizza to remove: 'small', 'medium', or 'large'")] string size)
    {
        _log($"RemoveFromOrder(pizzaName: \"{pizzaName}\", size: \"{size}\")");

        if (!Enum.TryParse<PizzaSize>(size, ignoreCase: true, out var pizzaSize))
            return "Invalid size. Please use 'small', 'medium', or 'large'.";

        var item = _order.Items.FirstOrDefault(i =>
            i.Pizza.Name.Equals(pizzaName, StringComparison.OrdinalIgnoreCase) && i.Size == pizzaSize);

        if (item is null)
            return $"'{pizzaName}' ({size}) is not in your order.";

        _order.Items.Remove(item);
        if (_order.Items.Count == 0)
            _order.Status = OrderStatus.Empty;

        return $"Removed {pizzaName} ({size}) from your order.";
    }

    [Description("Get the current order summary showing all items, quantities, prices, and the total")]
    public string GetOrderSummary()
    {
        _log("GetOrderSummary()");

        if (_order.Items.Count == 0)
            return "Your order is empty. Ask me about the menu to get started!";

        var sb = new StringBuilder();
        sb.AppendLine($"Order #{_order.OrderId}");
        sb.AppendLine(new string('-', 40));

        foreach (var item in _order.Items)
            sb.AppendLine($"  {item.Quantity}x {item.Pizza.Name} ({item.Size}) — £{item.LineTotal:F2}");

        sb.AppendLine(new string('-', 40));
        sb.AppendLine($"  TOTAL: £{_order.Total:F2}");
        return sb.ToString();
    }

    [Description("Calculate how many pizzas are recommended for a group, broken down by dietary preference")]
    public string CalculateRecommendation(
        [Description("Total number of people in the group")] int totalPeople,
        [Description("Number of vegetarian people in the group")] int vegCount = 0,
        [Description("Number of non-vegetarian people in the group")] int nonVegCount = 0)
    {
        _log($"CalculateRecommendation(totalPeople: {totalPeople}, vegCount: {vegCount}, nonVegCount: {nonVegCount})");

        if (totalPeople < 1)
            return "Please provide a valid number of people.";

        if (vegCount == 0 && nonVegCount == 0)
        {
            vegCount = totalPeople / 2;
            nonVegCount = totalPeople - vegCount;
        }

        int vegLarges = (int)Math.Ceiling(vegCount / 3.0);
        int nonVegLarges = (int)Math.Ceiling(nonVegCount / 3.0);

        var sb = new StringBuilder();
        sb.AppendLine($"Recommendation for {totalPeople} people:");

        if (vegCount > 0)
        {
            var vegPizzas = PizzaMenu.GetByCategory(PizzaCategory.Veg).Take(3).ToList();
            sb.AppendLine($"  Veg ({vegCount} people): {vegLarges} large pizza(s)");
            sb.AppendLine($"  Suggestions: {string.Join(", ", vegPizzas.Select(p => p.Name))}");
        }

        if (nonVegCount > 0)
        {
            var nonVegPizzas = PizzaMenu.GetByCategory(PizzaCategory.NonVeg).Take(3).ToList();
            sb.AppendLine($"  Non-veg ({nonVegCount} people): {nonVegLarges} large pizza(s)");
            sb.AppendLine($"  Suggestions: {string.Join(", ", nonVegPizzas.Select(p => p.Name))}");
        }

        int totalPizzas = vegLarges + nonVegLarges;
        decimal estimatedCost = totalPizzas * 15m;
        sb.AppendLine($"  Total: ~{totalPizzas} large pizzas, estimated £{estimatedCost:F2}–£{estimatedCost + totalPizzas * 2:F2}");
        return sb.ToString();
    }

    [Description("Confirm and place the current order. Only call this after the customer has explicitly said yes to confirming.")]
    public string ConfirmOrder()
    {
        _log("ConfirmOrder()");

        if (_order.Items.Count == 0)
            return "There's nothing in your order to confirm. Add some pizzas first!";

        if (_order.Status == OrderStatus.Confirmed)
            return $"Order #{_order.OrderId} has already been confirmed.";

        _order.Status = OrderStatus.Confirmed;
        return $"Order #{_order.OrderId} confirmed! Thank you — your pizzas will be ready in 25–30 minutes. Total charged: £{_order.Total:F2}";
    }

    [Description("Cancel the entire current order and clear all items")]
    public string CancelOrder()
    {
        _log("CancelOrder()");

        if (_order.Items.Count == 0 && _order.Status == OrderStatus.Empty)
            return "There's no active order to cancel.";

        _order.Items.Clear();
        _order.Status = OrderStatus.Cancelled;
        return "Order cancelled. Your order has been cleared. Let me know if you'd like to start a new order!";
    }
}
