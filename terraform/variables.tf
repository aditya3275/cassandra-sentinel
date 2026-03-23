variable "aws_region" {
  description = "AWS region"
  default     = "ap-south-1"
}

variable "instance_type_cassandra" {
  description = "EC2 instance type for Cassandra nodes"
  default     = "t3.medium"
}

variable "instance_type_platform" {
  description = "EC2 instance type for platform (Prometheus, Grafana, API)"
  default     = "t3.large"
}

variable "key_pair_name" {
  description = "AWS key pair name for SSH access"
  default     = "sentinel-key"
}

variable "project_name" {
  description = "Project name used for tagging"
  default     = "cassandra-sentinel"
}
