from django.urls import path
from .views import (
    ProductListCreateView, ProductRetrieveUpdateDestroyView, ProductBelowThresholdView,
    StockRequestListCreateView, StockRequestApproveView,
    BudgetRequestListCreateView, BudgetRequestValidateView, BudgetRequestRejectView, MyBudgetView,
    CategoryListCreateView, CategoryRetrieveUpdateDestroyView,
    DepartmentStockListView, DepartmentStockAssignView,
    StockMovementListView, StockReceptionView, StockTransferView,
    PurchaseOrderListCreateView, AvarieCreateView
)

urlpatterns = [
    path('products/', ProductListCreateView.as_view(), name='product-list-create'),
    path('products/<uuid:pk>/', ProductRetrieveUpdateDestroyView.as_view(), name='product-detail'),
    path('products/low-stock/', ProductBelowThresholdView.as_view(), name='low-stock'),
    path('stock-requests/', StockRequestListCreateView.as_view(), name='stock-request-list-create'),
    path('stock-requests/<uuid:pk>/approve/', StockRequestApproveView.as_view(), name='stock-request-approve'),
    path('my-budget/', MyBudgetView.as_view(), name='my-budget'),
    path('budget-requests/', BudgetRequestListCreateView.as_view(), name='budget-request-list-create'),
    path('budget-requests/<uuid:pk>/validate/', BudgetRequestValidateView.as_view(), name='budget-request-validate'),
    path('budget-requests/<uuid:pk>/reject/', BudgetRequestRejectView.as_view(), name='budget-request-reject'),
    path('department-stock/', DepartmentStockListView.as_view(), name='department-stock-list'),
    path('department-stock/assign/', DepartmentStockAssignView.as_view(), name='department-stock-assign'),
    path('movements/', StockMovementListView.as_view(), name='stock-movement-list'),
    path('receive/', StockReceptionView.as_view(), name='stock-receive'),
    path('transfer/', StockTransferView.as_view(), name='stock-transfer'),
    path('categories/', CategoryListCreateView.as_view(), name='category-list-create'),
    path('categories/<uuid:pk>/', CategoryRetrieveUpdateDestroyView.as_view(), name='category-detail'),
    path('purchase-orders/', PurchaseOrderListCreateView.as_view(), name='purchase-order-list-create'),
    path('avaries/', AvarieCreateView.as_view(), name='avarie-list-create'),
]
