namespace PizzaAgent.Core.Models;

public class OrderItem
{
    public required Pizza Pizza { get; init; }
    public required PizzaSize Size { get; init; }
    public int Quantity { get; set; }
    public decimal UnitPrice => Pizza.Prices[Size];
    public decimal LineTotal => UnitPrice * Quantity;
}
