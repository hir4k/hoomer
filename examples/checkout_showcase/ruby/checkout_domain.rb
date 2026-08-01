# frozen_string_literal: true

module CheckoutDomain
  Customer = Struct.new(
    :name,
    :email,
    :country,
    :premium,
    :loyalty_points,
    keyword_init: true
  )

  Product = Struct.new(:name, :price_cents, :available, keyword_init: true)
  OrderItem = Struct.new(:product, :quantity, keyword_init: true)
  ValidatedOrder = Struct.new(:items, keyword_init: true)
  InventoryReserved = Struct.new(:items, keyword_init: true)
  PaymentApproved = Struct.new(:amount_cents, keyword_init: true)

  Receipt = Struct.new(
    :customer_name,
    :customer_level,
    :subtotal_cents,
    :discount_cents,
    :charged_cents,
    :coupon_code,
    keyword_init: true
  )

  ValidationError = Struct.new(:message, keyword_init: true)
  InventoryError = Struct.new(
    :product_name,
    :requested,
    :available,
    keyword_init: true
  )
  PaymentError = Struct.new(:message, keyword_init: true)
  NotificationSent = Struct.new(:channel, keyword_init: true)
  NotificationError = Struct.new(:message, keyword_init: true)
  UnexpectedCheckoutError = Struct.new(:message, keyword_init: true)
end
