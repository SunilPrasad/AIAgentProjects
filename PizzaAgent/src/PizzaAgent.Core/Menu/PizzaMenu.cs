using PizzaAgent.Core.Models;

namespace PizzaAgent.Core.Menu;

public static class PizzaMenu
{
    public static readonly IReadOnlyList<Pizza> All =
    [
        // Veg
        new Pizza
        {
            Name = "Margherita",
            Category = PizzaCategory.Veg,
            Description = "Classic tomato sauce, fresh mozzarella, basil",
            Prices = new() { [PizzaSize.Small] = 7.99m, [PizzaSize.Medium] = 9.99m, [PizzaSize.Large] = 12.99m }
        },
        new Pizza
        {
            Name = "Veggie Supreme",
            Category = PizzaCategory.Veg,
            Description = "Roasted peppers, mushrooms, onions, olives, sweetcorn",
            Prices = new() { [PizzaSize.Small] = 9.49m, [PizzaSize.Medium] = 11.49m, [PizzaSize.Large] = 14.49m }
        },
        new Pizza
        {
            Name = "Mushroom & Truffle",
            Category = PizzaCategory.Veg,
            Description = "Wild mushrooms, truffle oil, parmesan, rosemary",
            Prices = new() { [PizzaSize.Small] = 10.49m, [PizzaSize.Medium] = 12.49m, [PizzaSize.Large] = 15.49m }
        },
        new Pizza
        {
            Name = "Garden Fresh",
            Category = PizzaCategory.Veg,
            Description = "Spinach, sun-dried tomatoes, artichoke, feta cheese",
            Prices = new() { [PizzaSize.Small] = 9.99m, [PizzaSize.Medium] = 11.99m, [PizzaSize.Large] = 14.99m }
        },
        new Pizza
        {
            Name = "Spicy Arrabbiata",
            Category = PizzaCategory.Veg,
            Description = "Spicy tomato sauce, chilli flakes, olives, capers",
            Prices = new() { [PizzaSize.Small] = 9.49m, [PizzaSize.Medium] = 11.49m, [PizzaSize.Large] = 14.49m }
        },

        // Non-Veg
        new Pizza
        {
            Name = "Pepperoni Classic",
            Category = PizzaCategory.NonVeg,
            Description = "Generous pepperoni, tomato sauce, mozzarella",
            Prices = new() { [PizzaSize.Small] = 9.99m, [PizzaSize.Medium] = 11.99m, [PizzaSize.Large] = 14.99m }
        },
        new Pizza
        {
            Name = "BBQ Chicken",
            Category = PizzaCategory.NonVeg,
            Description = "Smoky BBQ sauce, grilled chicken, red onion, coriander",
            Prices = new() { [PizzaSize.Small] = 10.49m, [PizzaSize.Medium] = 12.49m, [PizzaSize.Large] = 15.49m }
        },
        new Pizza
        {
            Name = "Meat Feast",
            Category = PizzaCategory.NonVeg,
            Description = "Pepperoni, beef meatballs, ham, spicy sausage",
            Prices = new() { [PizzaSize.Small] = 11.49m, [PizzaSize.Medium] = 13.49m, [PizzaSize.Large] = 16.49m }
        },
        new Pizza
        {
            Name = "Chicken Tikka",
            Category = PizzaCategory.NonVeg,
            Description = "Tandoori chicken, peppers, onions, mint yoghurt base",
            Prices = new() { [PizzaSize.Small] = 10.99m, [PizzaSize.Medium] = 12.99m, [PizzaSize.Large] = 15.99m }
        },
        new Pizza
        {
            Name = "Prawn & Chilli",
            Category = PizzaCategory.NonVeg,
            Description = "King prawns, garlic butter, chilli, cherry tomatoes",
            Prices = new() { [PizzaSize.Small] = 11.99m, [PizzaSize.Medium] = 13.99m, [PizzaSize.Large] = 16.99m }
        },
    ];

    public static Pizza? FindByName(string name) =>
        All.FirstOrDefault(p => p.Name.Equals(name, StringComparison.OrdinalIgnoreCase));

    public static IEnumerable<Pizza> GetByCategory(PizzaCategory category) =>
        All.Where(p => p.Category == category);
}
