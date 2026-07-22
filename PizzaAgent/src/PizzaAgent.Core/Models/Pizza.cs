namespace PizzaAgent.Core.Models;

public enum PizzaCategory { Veg, NonVeg }

public enum PizzaSize { Small, Medium, Large }

public class Pizza
{
    public required string Name { get; init; }
    public required PizzaCategory Category { get; init; }
    public required Dictionary<PizzaSize, decimal> Prices { get; init; }
    public required string Description { get; init; }
}
