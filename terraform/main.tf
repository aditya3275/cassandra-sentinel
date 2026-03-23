terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ── SSH Key Pair ──────────────────────────────────────────────────────────────
resource "aws_key_pair" "sentinel" {
  key_name   = var.key_pair_name
  public_key = file("~/.ssh/sentinel-key.pub")

  tags = {
    Project = var.project_name
  }
}

# ── VPC ───────────────────────────────────────────────────────────────────────
resource "aws_vpc" "sentinel" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name    = "${var.project_name}-vpc"
    Project = var.project_name
  }
}

# ── Internet Gateway ──────────────────────────────────────────────────────────
resource "aws_internet_gateway" "sentinel" {
  vpc_id = aws_vpc.sentinel.id

  tags = {
    Name    = "${var.project_name}-igw"
    Project = var.project_name
  }
}

# ── Public Subnet ─────────────────────────────────────────────────────────────
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.sentinel.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true

  tags = {
    Name    = "${var.project_name}-public-subnet"
    Project = var.project_name
  }
}

# ── Route Table ───────────────────────────────────────────────────────────────
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.sentinel.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.sentinel.id
  }

  tags = {
    Name    = "${var.project_name}-rt"
    Project = var.project_name
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ── Security Group ────────────────────────────────────────────────────────────
resource "aws_security_group" "sentinel" {
  name        = "${var.project_name}-sg"
  description = "Cassandra Sentinel security group"
  vpc_id      = aws_vpc.sentinel.id

  # SSH
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Cassandra CQL
  ingress {
    from_port   = 9042
    to_port     = 9042
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # Cassandra internode
  ingress {
    from_port   = 7000
    to_port     = 7001
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # JMX exporter
  ingress {
    from_port   = 9103
    to_port     = 9105
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # Prometheus
  ingress {
    from_port   = 9090
    to_port     = 9090
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Grafana
  ingress {
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # FastAPI
  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # All outbound
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project_name}-sg"
    Project = var.project_name
  }
}

# ── IAM Role for EC2 ──────────────────────────────────────────────────────────
resource "aws_iam_role" "sentinel" {
  name = "${var.project_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.sentinel.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "sentinel" {
  name = "${var.project_name}-instance-profile"
  role = aws_iam_role.sentinel.name
}

# ── Cassandra Node 1 ──────────────────────────────────────────────────────────
resource "aws_instance" "cassandra_node1" {
  ami                    = "ami-0f58b397bc5c1f2e8"
  instance_type          = var.instance_type_cassandra
  key_name               = aws_key_pair.sentinel.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.sentinel.id]
  iam_instance_profile   = aws_iam_instance_profile.sentinel.name

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    apt-get update -y
    apt-get install -y docker.io docker-compose-v2
    systemctl start docker
    systemctl enable docker
    usermod -aG docker ubuntu
  EOF

  tags = {
    Name    = "${var.project_name}-cassandra-node1"
    Project = var.project_name
    Role    = "cassandra"
  }
}

# ── Cassandra Node 2 ──────────────────────────────────────────────────────────
resource "aws_instance" "cassandra_node2" {
  ami                    = "ami-0f58b397bc5c1f2e8"
  instance_type          = var.instance_type_cassandra
  key_name               = aws_key_pair.sentinel.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.sentinel.id]
  iam_instance_profile   = aws_iam_instance_profile.sentinel.name

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    apt-get update -y
    apt-get install -y docker.io docker-compose-v2
    systemctl start docker
    systemctl enable docker
    usermod -aG docker ubuntu
  EOF

  tags = {
    Name    = "${var.project_name}-cassandra-node2"
    Project = var.project_name
    Role    = "cassandra"
  }
}

# ── Cassandra Node 3 ──────────────────────────────────────────────────────────
resource "aws_instance" "cassandra_node3" {
  ami                    = "ami-0f58b397bc5c1f2e8"
  instance_type          = var.instance_type_cassandra
  key_name               = aws_key_pair.sentinel.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.sentinel.id]
  iam_instance_profile   = aws_iam_instance_profile.sentinel.name

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    apt-get update -y
    apt-get install -y docker.io docker-compose-v2
    systemctl start docker
    systemctl enable docker
    usermod -aG docker ubuntu
  EOF

  tags = {
    Name    = "${var.project_name}-cassandra-node3"
    Project = var.project_name
    Role    = "cassandra"
  }
}

# ── Platform Node (Prometheus + Grafana + API) ────────────────────────────────
resource "aws_instance" "platform" {
  ami                    = "ami-0f58b397bc5c1f2e8"
  instance_type          = var.instance_type_platform
  key_name               = aws_key_pair.sentinel.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.sentinel.id]
  iam_instance_profile   = aws_iam_instance_profile.sentinel.name

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    apt-get update -y
    apt-get install -y docker.io docker-compose-v2 python3-pip python3-venv git
    systemctl start docker
    systemctl enable docker
    usermod -aG docker ubuntu
    pip3 install opa-client
  EOF

  tags = {
    Name    = "${var.project_name}-platform"
    Project = var.project_name
    Role    = "platform"
  }
}
