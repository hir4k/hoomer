# frozen_string_literal: true

require_relative "checkout_domain"

module Checkout
  include CheckoutDomain

  PAYMENT_LIMIT_CENTS = 10_000
  LOYALTY_BONUS = 10

  module_function

  def create_customer(
    name,
    email:,
    country: "India",
    premium: false,
    loyalty_points: 0
  )
    Customer.new(
      name:,
      email: email.strip.downcase,
      country:,
      premium:,
      loyalty_points:
    )
  end

  def validate_order(items)
    items.each do |item|
      next if item.quantity.positive?

      return ValidationError.new(
        message: "#{item.product.name} quantity must be positive"
      )
    end

    ValidatedOrder.new(items:)
  end

  def reserve_inventory(order)
    order.items.each do |item|
      next unless item.quantity > item.product.available

      return InventoryError.new(
        product_name: item.product.name,
        requested: item.quantity,
        available: item.product.available
      )
    end

    InventoryReserved.new(items: order.items)
  end

  def calculate_subtotal(items)
    items.sum { |item| item.product.price_cents * item.quantity }
  end

  def international?(customer)
    customer.country != "India"
  end

  def calculate_discount(customer, subtotal_cents, coupon_code = nil)
    return 0 if international?(customer)

    if coupon_code == "HUMAN10"
      subtotal_cents / 10
    elsif customer.premium
      subtotal_cents / 20
    else
      0
    end
  end

  def describe_coupon(coupon_code)
    case coupon_code
    when "HUMAN10"
      "HUMAN10"
    when nil
      "none"
    else
      "#{coupon_code} (unrecognized)"
    end
  end

  def charge_payment(amount_cents, limit_cents: PAYMENT_LIMIT_CENTS)
    if amount_cents > limit_cents
      return PaymentError.new(
        message: "Payment declined for #{amount_cents} cents"
      )
    end

    PaymentApproved.new(amount_cents:)
  end

  def customer_level(customer)
    if customer.loyalty_points >= 100
      "gold"
    elsif customer.loyalty_points >= 50
      "silver"
    else
      "new"
    end
  end

  def reward_customer(customer)
    customer.loyalty_points += LOYALTY_BONUS
  end

  def notify_warehouse(receipt)
    if receipt.charged_cents.negative?
      return NotificationError.new(
        message: "Cannot notify the warehouse about a refund"
      )
    end

    NotificationSent.new(channel: "warehouse")
  end

  def divider(width)
    return "" if width <= 0

    "-" + divider(width - 1)
  end

  def audit(label)
    puts "Audit started: #{label}"
    yield
    puts "Audit finished: #{label}"
  end

  def checkout(
    customer,
    items,
    coupon_code = nil,
    payment_limit_cents: PAYMENT_LIMIT_CENTS
  )
    validation_result = validate_order(items)
    validated_order = case validation_result
                      when ValidatedOrder then validation_result
                      when ValidationError then return validation_result
                      else
                        return UnexpectedCheckoutError.new(
                          message: "Validation returned an unknown value"
                        )
                      end

    inventory_result = reserve_inventory(validated_order)
    reserved_inventory = case inventory_result
                         when InventoryReserved then inventory_result
                         when InventoryError then return inventory_result
                         else
                           return UnexpectedCheckoutError.new(
                             message: "Inventory returned an unknown value"
                           )
                         end

    subtotal_cents = calculate_subtotal(reserved_inventory.items)
    discount_cents = calculate_discount(
      customer,
      subtotal_cents,
      coupon_code
    )
    charged_cents = subtotal_cents - discount_cents

    payment_result = charge_payment(
      charged_cents,
      limit_cents: payment_limit_cents
    )
    payment = case payment_result
              when PaymentApproved then payment_result
              when PaymentError then return payment_result
              else
                return UnexpectedCheckoutError.new(
                  message: "Payment returned an unknown value"
                )
              end

    reward_customer(customer)

    Receipt.new(
      customer_name: customer.name,
      customer_level: customer_level(customer),
      subtotal_cents:,
      discount_cents:,
      charged_cents: payment.amount_cents,
      coupon_code:
    )
  end

  def show_result(result)
    case result
    when Receipt
      puts "Approved for #{result.customer_name} (#{result.customer_level})"
      puts "Subtotal: #{result.subtotal_cents} cents"
      puts "Discount: #{result.discount_cents} cents"
      puts "Charged: #{result.charged_cents} cents"
      puts "Coupon: #{describe_coupon(result.coupon_code)}"
      notify_warehouse(result)
    when ValidationError
      puts "Invalid order: #{result.message}"
    when InventoryError
      puts "Not enough #{result.product_name}: " \
           "requested #{result.requested}, available #{result.available}"
    when PaymentError
      puts result.message
    else
      puts "Unexpected checkout result"
    end
  end

  def show_language_metadata(sample_product)
    fields = sample_product.class.members.map(&:to_s)
    parameters = method(:checkout).parameters.map { |_, name| name.to_s }

    puts "Reflected struct: #{sample_product.class.name.split('::').last} #{fields}"
    puts "Reflected function: checkout #{parameters}"
  end

  def run
    keyboard = Product.new(name: "Keyboard", price_cents: 2_500, available: 2)
    mouse = Product.new(name: "Mouse", price_cents: 900, available: 5)
    monitor = Product.new(name: "Monitor", price_cents: 12_000, available: 1)

    customer = create_customer(
      "Hirak",
      email: "  HIRAK@EXAMPLE.COM  ",
      premium: true,
      loyalty_points: 95
    )

    puts divider(42)
    puts "Customer: #{customer.name} <#{customer.email}>"
    show_language_metadata(keyboard)

    audit("three checkout attempts") do
      successful_items = [
        OrderItem.new(product: keyboard, quantity: 1),
        OrderItem.new(product: mouse, quantity: 1)
      ]
      successful_result = checkout(customer, successful_items, "HUMAN10")
      show_result(successful_result)

      puts
      unavailable_items = [OrderItem.new(product: keyboard, quantity: 3)]
      unavailable_result = checkout(customer, unavailable_items)
      show_result(unavailable_result)

      puts
      expensive_items = [OrderItem.new(product: monitor, quantity: 1)]
      payment_result = checkout(
        customer,
        expensive_items,
        payment_limit_cents: 10_000
      )
      show_result(payment_result)
    end

    (1..3).each do |day|
      next if day == 2

      puts "Tracking update: day #{day}"
    end
  end
end

Checkout.run if $PROGRAM_NAME == __FILE__
