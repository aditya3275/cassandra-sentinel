output "cassandra_node1_ip" {
  description = "Public IP of Cassandra Node 1"
  value       = aws_instance.cassandra_node1.public_ip
}

output "cassandra_node2_ip" {
  description = "Public IP of Cassandra Node 2"
  value       = aws_instance.cassandra_node2.public_ip
}

output "cassandra_node3_ip" {
  description = "Public IP of Cassandra Node 3"
  value       = aws_instance.cassandra_node3.public_ip
}

output "platform_ip" {
  description = "Public IP of Platform node"
  value       = aws_instance.platform.public_ip
}

output "grafana_url" {
  description = "Grafana dashboard URL"
  value       = "http://${aws_instance.platform.public_ip}:3000"
}

output "prometheus_url" {
  description = "Prometheus URL"
  value       = "http://${aws_instance.platform.public_ip}:9090"
}

output "api_url" {
  description = "FastAPI URL"
  value       = "http://${aws_instance.platform.public_ip}:8000"
}
