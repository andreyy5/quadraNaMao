from django.urls import path

from . import views

app_name = "agenda"

urlpatterns = [
    path("", views.AgendaDayView.as_view(), name="day"),
    path("semana/", views.AgendaWeekView.as_view(), name="week"),
    path("reservas/nova/", views.ReservaCreateView.as_view(), name="reserva_create"),
    path("reservas/valor/", views.ReservaQuoteView.as_view(), name="reserva_quote"),
    path("reservas/horarios/", views.ReservaSlotsView.as_view(), name="reserva_slots"),
    path("reservas/cancelar-lote/", views.ReservaBulkCancelView.as_view(), name="reserva_bulk_cancel"),
    path("reservas/<int:pk>/", views.ReservaDetailView.as_view(), name="reserva_detail"),
    path("reservas/<int:pk>/editar/", views.ReservaUpdateView.as_view(), name="reserva_update"),
    path("reservas/<int:pk>/cancelar/", views.ReservaCancelView.as_view(), name="reserva_cancel"),
    path("reservas/<int:pk>/status/", views.ReservaStatusView.as_view(), name="reserva_status"),
    path("bloqueios/", views.BloqueioListView.as_view(), name="bloqueio_list"),
    path("bloqueios/novo/", views.BloqueioCreateView.as_view(), name="bloqueio_create"),
    path("bloqueios/impacto/", views.BloqueioImpactView.as_view(), name="bloqueio_impact"),
    path("bloqueios/<int:pk>/remover/", views.BloqueioDeleteView.as_view(), name="bloqueio_delete"),
    path("bloqueios/avisar/", views.BloqueioAvisarView.as_view(), name="bloqueio_avisar"),
    path("mensalistas/", views.MensalistaListView.as_view(), name="mensalistas"),
    path("mensalistas/novo/", views.MensalistaCreateView.as_view(), name="mensalista_create"),
    path("mensalistas/<int:pk>/", views.MensalistaDetailView.as_view(), name="mensalista_detail"),
    path("mensalistas/<int:pk>/editar/", views.MensalistaUpdateView.as_view(), name="mensalista_update"),
    path(
        "mensalistas/<int:pk>/encerrar/", views.MensalistaEncerrarView.as_view(), name="mensalista_encerrar"
    ),
    path(
        "mensalistas/avisos/<int:pk>/resolver/", views.MensalistaAvisoView.as_view(), name="mensalista_aviso"
    ),
]
