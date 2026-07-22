namespace PizzaAgent.Core.Models;

public enum OrderStatus { Empty, Building, Confirmed, Cancelled }

public class Order
{
    public string OrderId { get; } = $"ORD-{Random.Shared.Next(1000, 9999)}";
    public List<OrderItem> Items { get; } = [];
    public OrderStatus Status { get; set; } = OrderStatus.Empty;
    public decimal Total => Items.Sum(i => i.LineTotal);
}
